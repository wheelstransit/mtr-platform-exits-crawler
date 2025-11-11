#!/usr/bin/env python3
import json
import os
import sys
import unicodedata
import re
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import itertools

import requests
import pandas as pd
from tqdm import tqdm
import polyline


class MTRCrawler:
    CSV_URL = "https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv"
    VENUE_URL = "https://mapapi.hkmapservice.gov.hk/ogc/wfs/indoor/mtr_venue_polygon?service=WFS&version=1.1.0&request=GetFeature&outputFormat=application%2Fjson"
    AMENITY_URL = "https://mapapi.hkmapservice.gov.hk/ogc/wfs/indoor/mtr_amenity_point?service=WFS&version=1.1.0&request=GetFeature&outputFormat=application%2Fjson"
    ROUTE_API_URL = "https://mapapi.hkmapservice.gov.hk/PedRoute/NAServer/route/solve"
    DATA_DIR = Path("data")
    RAW_DIR = DATA_DIR / "raw"
    OUTPUT_DIR = DATA_DIR / "output"
    
    def __init__(self):
        """Initialize the crawler"""
        self._setup_directories()
        self.df = None
        self.stations = {}
        self.lines = {}
        self.venue_data = None
        self.amenity_data_by_venue = {}
        self.exits = {}
        self.platforms = {}
        self.journeys = []
        self.platform_journeys = []
        self.line_name_to_code = {}
        self.line_name_lower_to_code = {}
        self.station_name_lower_to_code = {}
        self.destination_aliases = {}
        self.line_directions = defaultdict(lambda: defaultdict(list))
        self.unmatched_platforms = []
        
    def _setup_directories(self):
        """Create necessary directories"""
        self.RAW_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (self.OUTPUT_DIR / "geojson").mkdir(exist_ok=True)
        (self.OUTPUT_DIR / "csv").mkdir(exist_ok=True)
        
    def download_csv(self) -> Path:
        """Download the MTR stations CSV file"""
        print(f"Downloading MTR data from {self.CSV_URL}...")
        response = requests.get(self.CSV_URL)
        response.raise_for_status()
        csv_path = self.RAW_DIR / "mtr_lines_and_stations.csv"
        csv_path.write_bytes(response.content)
        print(f"✓ Downloaded to {csv_path}")
        return csv_path
        
    def download_venue_data(self) -> Path:
        """Download the MTR venue polygon data from HK Map Service"""
        print(f"\nDownloading venue data from HK Map Service...")
        response = requests.get(self.VENUE_URL)
        response.raise_for_status()
        venue_path = self.RAW_DIR / "mtr_venue_polygon.json"
        venue_path.write_bytes(response.content)
        print(f"✓ Downloaded to {venue_path}")
        return venue_path
    
    def load_venue_data(self, venue_path: Path = None):
        """Load venue polygon data"""
        venue_path = venue_path or self.RAW_DIR / "mtr_venue_polygon.json"
        if not venue_path.exists():
            venue_path = self.download_venue_data()
        
        print(f"Loading venue data from {venue_path}...")
        with open(venue_path, 'r', encoding='utf-8') as f:
            self.venue_data = json.load(f)
        print(f"✓ Loaded {len(self.venue_data.get('features', []))} venue features")
    
    def fetch_amenities_for_venue(self, venue_id: str) -> dict:
        """Fetch amenity data for a specific venue."""
        url = f"{self.AMENITY_URL}&cql_filter=venue_id%3D%27{venue_id}%27"
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.json()

    def _fetch_all_amenities_parallel(self, venue_ids: set):
        """Fetch amenities for all given venue IDs in parallel with a progress bar."""
        print(f"\nFetching amenities for {len(venue_ids)} venues in parallel...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_venue = {executor.submit(self.fetch_amenities_for_venue, venue_id): venue_id for venue_id in venue_ids}
            
            progress = tqdm(as_completed(future_to_venue), total=len(venue_ids), desc="Fetching amenities", unit="venue")
            
            for future in progress:
                venue_id = future_to_venue[future]
                try:
                    data = future.result()
                    features = data.get('features', [])
                    if features:
                        self.amenity_data_by_venue[venue_id] = features
                except Exception as e:
                    tqdm.write(f"  [!] Skipping venue {venue_id} due to error: {e}")
        
        print(f"✓ Fetched amenities for {len(self.amenity_data_by_venue)} venues successfully.")

    def load_data(self, csv_path: Path = None):
        """Load and parse the CSV data"""
        csv_path = csv_path or self.RAW_DIR / "mtr_lines_and_stations.csv"
        if not csv_path.exists():
            csv_path = self.download_csv()
            
        print(f"Loading data from {csv_path}...")
        self.df = pd.read_csv(csv_path)
        print(f"✓ Loaded {len(self.df)} records")
        
    def process_stations(self):
        """Process station data from the CSV"""
        print("\nProcessing stations...")
        station_data = defaultdict(lambda: {"lines": set(), "station_ids": set()})
        
        for _, row in self.df.iterrows():
            if pd.isna(row["Station Code"]) or pd.isna(row["English Name"]):
                continue
            code = row["Station Code"]
            station_data[code]["station_code"] = code
            station_data[code]["station_ids"].add(str(row["Station ID"]))
            station_data[code]["chinese_name"] = row["Chinese Name"]
            station_data[code]["english_name"] = row["English Name"]
            station_data[code]["lines"].add(row["Line Code"])
        
        for code, data in station_data.items():
            self.stations[code] = {
                "station_code": data["station_code"],
                "station_ids": sorted(list(data["station_ids"])),
                "name_en": data["english_name"],
                "name_zh": data["chinese_name"],
                "lines": sorted(list(data["lines"])),
                "interchange": len(data["lines"]) > 1,
                "location": {"lat": None, "lon": None},
                "exits": [],
                "platforms": []
            }
        print(f"✓ Processed {len(self.stations)} unique stations")
    
    def enrich_stations_with_venue_data(self):
        """Enrich station data with venue coordinates and IDs"""
        if not self.venue_data:
            print("\n⚠ Skipping venue data enrichment - no venue data loaded")
            return
        
        print("\nEnriching stations with venue data...")
        venue_map = {}
        for feature in self.venue_data.get('features', []):
            props = feature.get('properties', {})
            venue_name = (props.get('venue_name_en') or '').lower().replace(' station', '').strip()
            bbox = props.get('bbox')
            if venue_name and bbox and len(bbox) == 4:
                venue_map[venue_name] = {
                    'venue_id': props.get('venue_id'),
                    'lat': (bbox[1] + bbox[3]) / 2,
                    'lon': (bbox[0] + bbox[2]) / 2,
                    'bbox': bbox
                }
        
        matched, unmatched = 0, []
        for station in self.stations.values():
            name_norm = (station.get('name_en') or '').lower().strip()
            if name_norm in venue_map:
                venue = venue_map[name_norm]
                station.update({
                    'location': {'lat': venue['lat'], 'lon': venue['lon']},
                    'venue_id': venue['venue_id'],
                    'bbox': bbox
                })
                matched += 1
            else:
                unmatched.append(station['name_en'])
        
        print(f"✓ Matched {matched}/{len(self.stations)} stations with venue data")
        if unmatched:
            print(f"  ⚠ Unmatched: {', '.join(unmatched[:10])}{'...' if len(unmatched) > 10 else ''}")

    def process_exits(self):
        """Process exit data: gather, deduplicate generic exits, and link to stations."""
        print("\nProcessing exits...")
        if not self.amenity_data_by_venue:
            print("  ⚠ No amenity data available. Skipping.")
            return

        all_exits = {}
        exits_by_venue = defaultdict(list)
        for venue_id, features in self.amenity_data_by_venue.items():
            for feature in features:
                props = feature.get('properties', {})
                name_en = props.get('amenity_name_en') or ''
                if props.get('amenity_category') != 'entry' or 'exit' not in name_en.lower():
                    continue

                if not feature.get('geometry') or len(feature['geometry'].get('coordinates', [])) < 3:
                    continue
                
                coords = feature['geometry']['coordinates']
                exit_data = {
                    'amenity_id': props.get('amenity_id'),
                    'name_en': unicodedata.normalize('NFKC', name_en).strip(),
                    'name_zh': unicodedata.normalize('NFKC', props.get('amenity_name_zh') or '').strip(),
                    'coordinates': {'lon': coords[0], 'lat': coords[1], 'z': coords[2]},
                    'venue_id': venue_id
                }
                key = f"{venue_id}_{exit_data['name_en']}"
                all_exits[key] = exit_data
                exits_by_venue[venue_id].append(exit_data)
        
        keys_to_remove = set()
        for venue_id, exit_list in exits_by_venue.items():
            exit_names = [e['name_en'] for e in exit_list]
            letters_with_numbers = {name[5] for name in exit_names if name.startswith('Exit ') and len(name) > 6 and name[6].isdigit()}
            
            for exit_item in exit_list:
                name = exit_item['name_en']
                if name.startswith('Exit ') and len(name) == 6 and name[5] in letters_with_numbers:
                    keys_to_remove.add(f"{venue_id}_{name}")
        
        self.exits = {key: value for key, value in all_exits.items() if key not in keys_to_remove}
        print(f"✓ Processed {len(self.exits)} final unique exits.")

        for station in self.stations.values():
            venue_id = station.get('venue_id')
            if not venue_id: continue
            
            station_exit_names = [e['name_en'] for e in self.exits.values() if e['venue_id'] == venue_id]
            station['exits'] = sorted(station_exit_names)

    def process_platforms(self):
        """
        Process platform data. If a single feature contains multiple platform numbers,
        create a separate entry for each one with a cleaned name.
        """
        print("\nProcessing platforms...")
        if not self.amenity_data_by_venue:
            print("  ⚠ No amenity data available. Skipping.")
            return

        for venue_id, features in self.amenity_data_by_venue.items():
            for feature in features:
                props = feature.get('properties', {})
                if props.get('amenity_category') != 'platform' or not feature.get('geometry'):
                    continue

                original_name_en = unicodedata.normalize('NFKC', props.get('amenity_name_en') or '')
                coords = feature['geometry'].get('coordinates', [])
                if len(coords) < 3: continue
                
                platform_numbers = []
                platform_match = re.match(r'Platform[s]?\s*([\d,\s&]+)', original_name_en, re.IGNORECASE)
                
                if platform_match:
                    platform_numbers = re.findall(r'\d+', platform_match.group(1))
                else:
                    found_numbers = re.findall(r'^\d+', original_name_en)
                    if found_numbers: platform_numbers.append(found_numbers[0])

                if not platform_numbers: continue

                base_platform_data = {
                    'amenity_id': props.get('amenity_id'),
                    'name_zh': unicodedata.normalize('NFKC', props.get('amenity_name_zh') or ''),
                    'coordinates': {'lon': coords[0], 'lat': coords[1], 'z': coords[2]},
                    'venue_id': venue_id
                }

                for ref in platform_numbers:
                    key = f"{venue_id}_platform_{ref}"
                    platform_data = base_platform_data.copy()
                    platform_data['ref'] = ref
                    
                    if platform_match:
                        original_platform_text = platform_match.group(0)
                        platform_data['name_en'] = original_name_en.replace(original_platform_text, f"Platform {ref}").strip()
                    else:
                        platform_data['name_en'] = original_name_en

                    self.platforms[key] = platform_data

        print(f"✓ Processed {len(self.platforms)} unique platforms (after splitting merged entries).")

    def _build_lookup_tables(self):
        """Builds lookup dictionaries for matching platforms to lines."""
        self.line_name_to_code = {
            "Airport Express": "AEL", "Kwun Tong Line": "KTL",
            "Tsuen Wan Line": "TWL", "Island Line": "ISL",
            "Tung Chung Line": "TCL", "Tseung Kwan O Line": "TKL",
            "East Rail Line": "EAL", "Tuen Ma Line": "TML",
            "Disneyland Resort Line": "DRL", "South Island Line": "SIL"
        }
        self.line_name_lower_to_code = {k.lower(): v for k, v in self.line_name_to_code.items()}
        
        temp_station_map = self.df.drop_duplicates(subset='Station Code')
        self.station_name_lower_to_code = {
            row["English Name"].strip().lower(): row["Station Code"]
            for _, row in temp_station_map.iterrows()
            if pd.notna(row["English Name"]) and isinstance(row["English Name"], str)
        }
        
        self.destination_aliases = {'city': 'hong kong'}
        
        sorted_df = self.df.sort_values(by=["Line Code", "Direction", "Sequence"])
        for _, row in sorted_df.iterrows():
            if pd.notna(row['Line Code']) and pd.notna(row['Direction']) and pd.notna(row['Station Code']):
                self.line_directions[row['Line Code']][row['Direction']].append(row['Station Code'])

    def _find_directions_for_line(self, platform_data, line_code, destinations_str):
        """Helper to find and append directions for a given line code and destination string."""
        destinations = re.split(r'\s*/\s*|\s*&\s*', destinations_str)
        found_any = False
        for dest_station in destinations:
            clean_dest = re.sub(r'\s+', ' ', dest_station.strip()).lower()
            to_station_str_lower = self.destination_aliases.get(clean_dest, clean_dest)

            to_station_code = self.station_name_lower_to_code.get(to_station_str_lower)
            if not to_station_code: continue

            if line_code in self.line_directions:
                for direction, station_sequence in self.line_directions[line_code].items():
                    if station_sequence and station_sequence[-1] == to_station_code:
                        new_service = {
                            'line_code': line_code, 'direction': direction,
                            'destination_station_code': to_station_code
                        }
                        if new_service not in platform_data['lines_and_directions']:
                            platform_data['lines_and_directions'].append(new_service)
                            found_any = True
        return found_any

    def _find_terminating_direction(self, platform_data, line_code, current_station_code):
        """For 'End of Line' platforms, this finds the direction that ARRIVES at this station."""
        if line_code in self.line_directions:
            for direction, station_sequence in self.line_directions[line_code].items():
                if station_sequence and station_sequence[-1] == current_station_code:
                    destination_station_code = station_sequence[-1]
                    new_service = {
                        'line_code': line_code, 'direction': direction,
                        'destination_station_code': destination_station_code
                    }
                    if new_service not in platform_data['lines_and_directions']:
                        platform_data['lines_and_directions'].append(new_service)
                        return True
        return False

    def match_platforms_to_lines(self):
        """Matches platforms to lines and directions with extensive cleaning and fallback logic."""
        print("\nMatching platforms to lines and directions...")
        if self.df is None or not self.platforms:
            print("  ⚠ CSV data not loaded or no platforms processed. Skipping.")
            return

        self._build_lookup_tables()
        venue_id_to_station = {s['venue_id']: s for s in self.stations.values() if 'venue_id' in s}
        
        matched_count = 0
        for platform_key, platform_data in self.platforms.items():
            name_en = platform_data.get('name_en', '')
            platform_data['lines_and_directions'] = []

            cleaned_name = re.sub(r'\s+', ' ', name_en.strip())
            cleaned_name = re.sub(r'\bti\b', 'to', cleaned_name, flags=re.IGNORECASE)
            cleaned_name = re.sub(r'\bTuen Mum\b', 'Tuen Mun', cleaned_name, flags=re.IGNORECASE)
            cleaned_name = re.sub(r'\bTuen Ma\b', 'Tuen Mun', cleaned_name, flags=re.IGNORECASE)
            cleaned_name = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', cleaned_name)
            cleaned_name = re.sub(r'([a-zA-Z])(to|from|End)\b', r'\1 \2', cleaned_name, flags=re.IGNORECASE)
            cleaned_name = re.sub(r'\s+', ' ', cleaned_name).strip()
            
            was_matched = False
            service_desc = re.sub(r'Platform[s]?\s*[\d,\s&]+', '', cleaned_name, flags=re.IGNORECASE).strip()
            
            if service_desc.lower().startswith('to '):
                service_desc = service_desc[3:].strip()
            
            primary_match = re.search(r'(.+?)\s+to\s+(.+)', service_desc, re.IGNORECASE)
            if primary_match:
                line_name_str = re.sub(r'\s+', ' ', primary_match.group(1).strip()).lower()
                destinations_str = primary_match.group(2)
                destinations_str = re.sub(r'\s+\d+\s*$', '', destinations_str).strip()

                line_code = self.line_name_lower_to_code.get(line_name_str)
                if line_code and self._find_directions_for_line(platform_data, line_code, destinations_str):
                    was_matched = True
            
            ael_keywords = ['airport', 'asiaworld-expo', 'city']
            if not was_matched and any(keyword in service_desc.lower() for keyword in ael_keywords):
                line_code = 'AEL'
                if 'to or from' in cleaned_name.lower():
                    for direction, station_sequence in self.line_directions[line_code].items():
                        if station_sequence:
                            destination_code = station_sequence[-1]
                            new_service = {'line_code': line_code, 'direction': direction, 'destination_station_code': destination_code}
                            if new_service not in platform_data['lines_and_directions']:
                                platform_data['lines_and_directions'].append(new_service)
                                was_matched = True
                elif 'from' in cleaned_name.lower():
                    if self._find_directions_for_line(platform_data, line_code, 'Hong Kong'):
                        was_matched = True
                else:
                    if self._find_directions_for_line(platform_data, line_code, service_desc):
                        was_matched = True

            end_of_line_match = re.search(r'End of (?:the\s*)?(.+)', service_desc, re.IGNORECASE)
            if not was_matched and end_of_line_match:
                line_name_str = re.sub(r'\s+', ' ', end_of_line_match.group(1).strip()).lower()
                line_code = self.line_name_lower_to_code.get(line_name_str)
                
                venue_id = platform_data.get('venue_id')
                station = venue_id_to_station.get(venue_id)
                
                if line_code and station:
                    current_station_code = station['station_code']
                    if self._find_terminating_direction(platform_data, line_code, current_station_code):
                        was_matched = True

            if not was_matched:
                venue_id = platform_data.get('venue_id')
                station = venue_id_to_station.get(venue_id)
                
                if station and len(station['lines']) == 1:
                    line_code = station['lines'][0]
                    dest_match = re.search(r'(?:to)\s+(.+)', service_desc, re.IGNORECASE)
                    dest_str = dest_match.group(1) if dest_match else service_desc
                    if self._find_directions_for_line(platform_data, line_code, dest_str):
                        was_matched = True

            if was_matched:
                matched_count += 1
            else:
                self.unmatched_platforms.append((platform_key, name_en, "Pattern not matched or line/destination invalid"))

        print(f"✓ Matched {matched_count}/{len(self.platforms)} platforms with at least one line/direction.")
        if self.unmatched_platforms:
            print("  --- Unmatched Platforms ---")
            sorted_unmatched = sorted(self.unmatched_platforms, key=lambda x: x[2])
            for key, name, reason in sorted_unmatched:
                print(f"  [!] ID: {key}\n      Name: '{name}'\n      Reason: {reason}")
            print("  -------------------------")

    def _link_platforms_to_stations(self):
        """Iterates through platforms and links their keys back to the parent station objects."""
        print("\nLinking platforms to stations...")
        if not self.platforms:
            print("  ⚠ No platforms to link. Skipping.")
            return

        station_lookup = {s['venue_id']: s for s in self.stations.values() if 'venue_id' in s}
        
        for platform_key, platform_data in self.platforms.items():
            venue_id = platform_data.get('venue_id')
            if venue_id in station_lookup:
                station_lookup[venue_id]['platforms'].append(platform_key)
        
        for station in self.stations.values():
            station['platforms'].sort()

        print("✓ Linked platforms to stations.")
    
    def _apply_unmatched_service_fallback(self, unmatched_services):
        """
        For any service that couldn't be matched, apply it to the first available platform
        at the station, prioritizing platforms already serving that line.
        """
        print("\nApplying fallback logic for unmatched services...")
        applied_count = 0
        venue_id_to_station = {s['venue_id']: s for s in self.stations.values() if 'venue_id' in s}
        station_code_to_venue_id = {s['station_code']: s['venue_id'] for s in self.stations.values() if 'venue_id' in s}

        for station_code, line_code, direction in unmatched_services:
            venue_id = station_code_to_venue_id.get(station_code)
            if not venue_id:
                continue

            # 1. Get all platforms at this station
            station_platforms = {k: v for k, v in self.platforms.items() if v['venue_id'] == venue_id}
            if not station_platforms:
                continue
            
            # 2. Find a target platform
            target_platform_key = None

            # 2a. Prioritize platforms already serving this line
            line_platforms = []
            for key, plat in station_platforms.items():
                for service in plat.get('lines_and_directions', []):
                    if service.get('line_code') == line_code:
                        line_platforms.append(key)
                        break
            
            if line_platforms:
                target_platform_key = sorted(line_platforms)[0]
            else:
                # 2b. Fallback to the very first platform of the station
                target_platform_key = sorted(station_platforms.keys())[0]

            # 3. Apply the service to the target platform
            if target_platform_key:
                destination_station_code = self.line_directions[line_code][direction][-1]
                new_service = {
                    'line_code': line_code,
                    'direction': direction,
                    'destination_station_code': destination_station_code
                }
                self.platforms[target_platform_key]['lines_and_directions'].append(new_service)
                applied_count += 1
        
        if applied_count > 0:
            print(f"✓ Applied fallback logic to {applied_count} services.")

    def report_unmatched_services(self):
        """
        Compares all services in the CSV against matched platforms and reports the missing ones.
        """
        print("\n" + "="*60 + "\nUNMATCHED SERVICE REPORT\n" + "="*60)
        if self.df is None:
            print("  ⚠ Cannot generate report: Source CSV not loaded.")
            return
        
        # --- Stage 1: Initial Matching Report ---
        all_services = set()
        for _, row in self.df.iterrows():
            if pd.notna(row['Station Code']) and pd.notna(row['Line Code']) and pd.notna(row['Direction']):
                 line_stations = self.line_directions.get(row['Line Code'], {}).get(row['Direction'], [])
                 if line_stations and row['Station Code'] != line_stations[-1]:
                    all_services.add((row['Station Code'], row['Line Code'], row['Direction']))

        matched_services = set()
        venue_to_station_code = {s['venue_id']: s['station_code'] for s in self.stations.values() if 'venue_id' in s}
        for platform in self.platforms.values():
            station_code = venue_to_station_code.get(platform.get('venue_id'))
            if not station_code: continue
            for service in platform.get('lines_and_directions', []):
                if service['destination_station_code'] != station_code:
                    matched_services.add((station_code, service['line_code'], service['direction']))
        
        initial_unmatched = sorted(list(all_services - matched_services))
        
        # --- Stage 2: Apply Fallback ---
        if initial_unmatched:
            self._apply_unmatched_service_fallback(initial_unmatched)

        # --- Stage 3: Final Report ---
        final_matched_services = set()
        for platform in self.platforms.values():
            station_code = venue_to_station_code.get(platform.get('venue_id'))
            if not station_code: continue
            for service in platform.get('lines_and_directions', []):
                if service['destination_station_code'] != station_code:
                    final_matched_services.add((station_code, service['line_code'], service['direction']))

        final_unmatched = sorted(list(all_services - final_matched_services))

        if not final_unmatched:
            print("✓ All departing services from source data are now represented on a platform (including fallbacks).")
        else:
            print(f"[!] Found {len(final_unmatched)} services that are STILL unmatched (likely stations with no platforms):")
            unmatched_by_line = defaultdict(list)
            for station, line, direction in final_unmatched:
                unmatched_by_line[line].append((station, direction))
            
            for line, services in sorted(unmatched_by_line.items()):
                print(f"\n  --- Line: {line} ---")
                for station, direction in sorted(services):
                    station_name = next((s['name_en'] for s in self.stations.values() if s['station_code'] == station), station)
                    print(f"    - Station: {station_name} ({station}), Direction: {direction}")
        print("="*60)
        
    def _fetch_route(self, pair: dict) -> dict:
        """Generic worker function to fetch a route between two points."""
        start_point = pair['start']
        end_point = pair['end']

        start_coords = start_point['coordinates']
        end_coords = end_point['coordinates']

        stops_obj = { "features": [{ "geometry": {"x": start_coords['lon'], "y": start_coords['lat'], "z": start_coords['z']} }, { "geometry": {"x": end_coords['lon'], "y": end_coords['lat'], "z": end_coords['z']} }] }
        params = { 'stops': json.dumps(stops_obj, separators=(',', ':')), 'f': 'json', 'returnZ': 'true', 'outSR': 4326, 'travelMode': '3' }

        try:
            response = requests.get(self.ROUTE_API_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data and data.get('routes', {}).get('features'):
                route = data['routes']['features'][0]
                coords = [(p[1], p[0]) for path in route['geometry']['paths'] for p in path]
                
                # Base result, to be customized by journey type
                base_result = {
                    "station_code": pair['station_code'],
                    "walk_time_minutes": route['attributes']['Total_Time'],
                    "walk_distance_metres": route['attributes']['Total_Length'],
                    "google_polyline": polyline.encode(coords),
                }
                
                if pair['type'] == 'platform-exit':
                    base_result.update({
                        "platform_amenity_id": start_point['amenity_id'],
                        "exit_amenity_id": end_point['amenity_id'],
                    })
                elif pair['type'] == 'platform-platform':
                    base_result.update({
                        "start_platform_amenity_id": start_point['amenity_id'],
                        "end_platform_amenity_id": end_point['amenity_id'],
                    })
                return base_result
        except requests.exceptions.RequestException:
            pass
        return None

    def calculate_internal_journeys(self):
        """Calculate walking routes for platform-exits AND platform-platforms."""
        print("\nCalculating all internal station journeys...")
        
        venue_to_station_code = {s['venue_id']: s['station_code'] for s in self.stations.values() if 'venue_id' in s}
        all_pairs = []

        for venue_id, station_code in venue_to_station_code.items():
            station_platforms = [p for p in self.platforms.values() if p['venue_id'] == venue_id]
            station_exits = [e for e in self.exits.values() if e['venue_id'] == venue_id]
            
            # Platform -> Exit pairs
            for platform in station_platforms:
                for exit_item in station_exits:
                    all_pairs.append({"type": "platform-exit", "station_code": station_code, "start": platform, "end": exit_item})

            # Platform -> Platform pairs (permutations for both directions)
            if len(station_platforms) > 1:
                for p1, p2 in itertools.permutations(station_platforms, 2):
                     all_pairs.append({"type": "platform-platform", "station_code": station_code, "start": p1, "end": p2})

        if not all_pairs:
            print("  ⚠ No journey pairs found to calculate.")
            return

        print(f"  Found {len(all_pairs)} total journey pairs to calculate.")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_pair = {executor.submit(self._fetch_route, pair): pair for pair in all_pairs}
            
            progress = tqdm(as_completed(future_to_pair), total=len(all_pairs), desc="Calculating routes", unit="route")
            
            for future in progress:
                pair = future_to_pair[future]
                result = future.result()
                if result:
                    if pair['type'] == 'platform-exit':
                        self.journeys.append(result)
                    elif pair['type'] == 'platform-platform':
                        self.platform_journeys.append(result)

        print(f"✓ Successfully calculated {len(self.journeys)} platform-exit journeys.")
        print(f"✓ Successfully calculated {len(self.platform_journeys)} platform-platform journeys.")

    def export_json(self):
        """Export core data to JSON format"""
        print("\nExporting core data to JSON...")
        output = {
            "stations": self.stations,
            "exits": self.exits,
            "platforms": self.platforms
        }
        json_path = self.OUTPUT_DIR / "mtr_data_complete.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"✓ Exported to {json_path}")

    def export_journeys(self):
        """Export calculated platform-exit journey data to JSON format."""
        print("\nExporting Platform-Exit Journeys...")
        if not self.journeys:
            print("  ⚠ No platform-exit journeys to export.")
            return
            
        json_path = self.OUTPUT_DIR / "journeys.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.journeys, f, ensure_ascii=False, indent=2)
        print(f"✓ Exported {len(self.journeys)} journeys to {json_path}")
    
    def export_platform_journeys(self):
        """Export calculated platform-platform journey data to JSON format."""
        print("\nExporting Platform-Platform Journeys...")
        if not self.platform_journeys:
            print("  ⚠ No platform-platform journeys to export.")
            return
            
        json_path = self.OUTPUT_DIR / "platform_journeys.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.platform_journeys, f, ensure_ascii=False, indent=2)
        print(f"✓ Exported {len(self.platform_journeys)} journeys to {json_path}")
        
    def print_summary(self):
        """Print summary statistics"""
        print("\n" + "="*60 + "\nMTR DATA SUMMARY\n" + "="*60)
        print(f"Total Stations: {len(self.stations)}")
        print(f"Total Exits: {len(self.exits)}")
        print(f"Total Platforms: {len(self.platforms)}")
        if self.platforms:
             matched_platforms = len(self.platforms) - len(self.unmatched_platforms)
             print(f"  - Matched w/ Line/Direction: {matched_platforms}/{len(self.platforms)}")
        print(f"Total Journeys (Platform-Exit): {len(self.journeys)}")
        print(f"Total Journeys (Platform-Platform): {len(self.platform_journeys)}")
        print(f"Interchange Stations: {sum(1 for s in self.stations.values() if s['interchange'])}")
        print("="*60)

    def run(self, calculate_journeys: bool = True):
        """Run the complete crawler pipeline"""
        print("="*60 + "\nMTR Platform Exits Crawler\n" + "="*60)
        try:
            self.load_data()
            self.load_venue_data()
            
            self.process_stations()
            self.enrich_stations_with_venue_data()
            
            venue_ids = {s.get('venue_id') for s in self.stations.values() if s.get('venue_id')}
            if venue_ids:
                self._fetch_all_amenities_parallel(venue_ids)
            
            self.process_exits()
            self.process_platforms()
            
            self.match_platforms_to_lines()
            self._link_platforms_to_stations()
            self.report_unmatched_services()
            
            if calculate_journeys:
                self.calculate_internal_journeys()
                self.export_journeys()
                self.export_platform_journeys()
            else:
                print("\nSkipping internal journey calculation as requested.")

            self.export_json()
            
            self.print_summary()
            
            print("\n✓ All done! Output files are in the 'data/output' directory.")
            return 0
            
        except Exception as e:
            print(f"\n✗ An unexpected error occurred: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

def main():
    """
    Run with `--no-journeys` to skip route calculation.
    """
    calculate_journeys = '--no-journeys' not in sys.argv
    crawler = MTRCrawler()
    return crawler.run(calculate_journeys=calculate_journeys)

if __name__ == "__main__":
    sys.exit(main())