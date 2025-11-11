# MTR Platform Exits Crawler - Project Structure

## Overview
A public domain crawler to collect comprehensive MTR station data including stations, routes, platforms, exits, and indoor navigation information with walking times and polylines.

## Data Sources

### Current Available Data
- **MTR Lines and Stations**: https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv
  - Line codes, station codes, station IDs, names (EN/ZH), sequences

### Data to be Collected (To Implement)
1. **Station Exit Locations** - GPS coordinates of each numbered exit
2. **Platform Information** - Platform numbers, directions, lines served
3. **Exit-to-Platform Routing** - Indoor walking paths and polylines
4. **Walking Time Data** - Time estimates between exits and platforms
5. **Station Layouts** - Floor plans and level information (if available)
6. **Accessibility Info** - Elevators, escalators, barrier-free routes

## Data Model

### 1. Stations
```json
{
  "station_id": "01",
  "station_code": "CEN",
  "name_en": "Central",
  "name_zh": "中環",
  "location": {
    "lat": 22.2816,
    "lon": 114.1577
  },
  "lines": ["ISL", "TWL"],
  "exits": ["A", "B", "C", "D1", "D2", "E", "F", "G", "H", "J1", "J2", "J3", "K"],
  "platforms": ["ISL-1", "ISL-2", "TWL-1", "TWL-2"],
  "interchange": true,
  "metadata": {
    "opened": "1980-02-12",
    "district": "Central and Western",
    "region": "Hong Kong Island"
  }
}
```

### 2. Exits
```json
{
  "exit_id": "CEN-A",
  "station_id": "01",
  "station_code": "CEN",
  "exit_number": "A",
  "name_en": "Exit A",
  "name_zh": "A出口",
  "location": {
    "lat": 22.2819,
    "lon": 114.1581
  },
  "level": "G",
  "facilities": ["escalator", "stairs"],
  "barrier_free": false,
  "nearby_landmarks": [
    "Chater Garden",
    "Prince's Building"
  ],
  "photos": []
}
```

### 3. Platforms
```json
{
  "platform_id": "CEN-ISL-1",
  "station_id": "01",
  "station_code": "CEN",
  "platform_number": "1",
  "line_code": "ISL",
  "direction": "Eastbound",
  "destination": "Chai Wan",
  "level": "L3",
  "location": {
    "lat": 22.2816,
    "lon": 114.1577
  }
}
```

### 4. Exit-to-Platform Routes
```json
{
  "route_id": "CEN-A-to-CEN-ISL-1",
  "station_id": "01",
  "station_code": "CEN",
  "from_exit": "CEN-A",
  "to_platform": "CEN-ISL-1",
  "walking_time_seconds": 180,
  "distance_meters": 120,
  "path_type": "indoor",
  "accessibility": {
    "wheelchair_accessible": false,
    "has_escalator": true,
    "has_elevator": false,
    "stairs_count": 2
  },
  "polyline": {
    "type": "LineString",
    "coordinates": [
      [114.1581, 22.2819, 0],
      [114.1580, 22.2818, -5],
      [114.1577, 22.2816, -15]
    ]
  },
  "instructions": [
    {
      "step": 1,
      "action": "enter",
      "description_en": "Enter from Exit A",
      "description_zh": "從A出口進入"
    },
    {
      "step": 2,
      "action": "escalator_down",
      "description_en": "Take escalator down",
      "description_zh": "乘扶手電梯向下"
    },
    {
      "step": 3,
      "action": "walk",
      "description_en": "Follow signs to Island Line Platform 1",
      "description_zh": "跟隨指示往港島線1號月台"
    }
  ]
}
```

### 5. Lines (Routes)
```json
{
  "line_code": "ISL",
  "name_en": "Island Line",
  "name_zh": "港島綫",
  "color": "#0075C2",
  "stations": ["KET", "HFC", "CHW", "SKW", "SWH", "TKW", "QUB", "TAK", "NOP", "FOH", "ADM", "CEN", "SHW", "HKU"],
  "directions": {
    "DT": {
      "name_en": "Eastbound (Kennedy Town → Chai Wan)",
      "name_zh": "東行 (堅尼地城 → 柴灣)"
    },
    "UT": {
      "name_en": "Westbound (Chai Wan → Kennedy Town)",
      "name_zh": "西行 (柴灣 → 堅尼地城)"
    }
  },
  "operator": "MTR Corporation"
}
```

## Crawler Implementation Plan

### Phase 1: Data Collection Preparation
- [ ] Set up Python crawler environment (requests, BeautifulSoup, Selenium)
- [ ] Study MTR website structure and identify data sources
- [ ] Set up data storage (SQLite/PostgreSQL for intermediate storage)
- [ ] Create rate limiting and ethical crawling policies

### Phase 2: Station & Exit Data Collection
- [ ] Parse existing CSV for base station data
- [ ] Crawl MTR website for exit information
  - Station pages: https://www.mtr.com.hk/en/customer/services/system_map.html
  - Individual station pages with exit maps
- [ ] Geocode exit locations using:
  - MTR published maps
  - OpenStreetMap data
  - Google Maps/HK Gov GeoInfo API (if needed)
- [ ] Extract exit facilities and accessibility info

### Phase 3: Platform Data Collection
- [ ] Identify platform numbers and directions per station
- [ ] Map platforms to lines and destinations
- [ ] Collect platform-level information (if available)

### Phase 4: Indoor Navigation Data
- [ ] Collect walking time estimates
  - Official MTR apps (if available via API)
  - Manual timing data collection
  - Crowdsourced data
- [ ] Generate indoor polylines:
  - Manual digitization from station maps
  - Path inference from known points
  - Integration with indoor mapping data (if available)

### Phase 5: Data Validation & Export
- [ ] Validate all collected data for completeness
- [ ] Cross-reference with OpenStreetMap MTR data
- [ ] Generate output in multiple formats
- [ ] Create documentation and metadata

## Output Data Formats

### Recommended Primary Format: GeoJSON
**Why GeoJSON:**
- Native support for geographic coordinates
- Industry standard for transit/mapping applications
- Easy visualization in mapping tools (QGIS, Mapbox, Leaflet, Google Maps)
- Supports both point data (exits, platforms) and line data (polylines)
- Self-documenting with embedded properties

**Output Files:**
- `stations.geojson` - All station locations and metadata
- `exits.geojson` - All exit points with properties
- `platforms.geojson` - Platform locations
- `exit_to_platform_routes.geojson` - Walking paths with polylines
- `lines.geojson` - Line routes with full geometry

### Secondary Formats

#### 1. CSV (for tabular data)
- `stations.csv`
- `exits.csv`
- `platforms.csv`
- `exit_platform_walking_times.csv`
- Easy for data analysis, spreadsheets, database imports

#### 2. JSON (for programmatic access)
- `mtr_data_complete.json` - Single file with all data
- Structured for API consumption
- Easier for web applications

#### 3. SQLite Database
- `mtr_data.db` - Relational database with all entities
- Good for complex queries and data integrity
- Portable single-file format

#### 4. GTFS-like Format (optional)
- If you want transit routing compatibility
- `stops.txt`, `routes.txt`, `stop_times.txt`, etc.
- Compatible with transit routing engines

## Technologies & Tools

### Crawler Stack
- **Python 3.9+**
  - `requests` - HTTP requests
  - `beautifulsoup4` - HTML parsing
  - `selenium` - Dynamic content handling
  - `pandas` - Data manipulation
  - `geopandas` - Geographic data handling
  - `geopy` - Geocoding
  - `shapely` - Geometry operations

### Data Storage
- **SQLite** - Development and intermediate storage
- **PostgreSQL + PostGIS** - Production (optional, for geographic queries)

### Data Validation
- **GeoJSON validation** - `geojsonlint`
- **Schema validation** - JSON Schema
- **Data quality checks** - Custom scripts

### Visualization & Testing
- **QGIS** - Desktop GIS for data verification
- **Leaflet/Mapbox** - Web mapping for preview
- **Jupyter Notebooks** - Data exploration and analysis

## File Structure

```
mtr-platform-exits-crawler/
├── LICENSE
├── README.md
├── STRUCTURE.md                    # This file
├── requirements.txt                # Python dependencies
├── .gitignore
│
├── data/
│   ├── raw/                        # Raw crawled data
│   │   ├── mtr_lines_and_stations.csv
│   │   ├── station_pages/          # HTML snapshots
│   │   └── exit_maps/              # Downloaded maps
│   │
│   ├── processed/                  # Cleaned and structured data
│   │   ├── stations.json
│   │   ├── exits.json
│   │   ├── platforms.json
│   │   └── routes.json
│   │
│   └── output/                     # Final export formats
│       ├── geojson/
│       │   ├── stations.geojson
│       │   ├── exits.geojson
│       │   ├── platforms.geojson
│       │   ├── exit_to_platform_routes.geojson
│       │   └── lines.geojson
│       │
│       ├── csv/
│       │   ├── stations.csv
│       │   ├── exits.csv
│       │   ├── platforms.csv
│       │   └── exit_platform_walking_times.csv
│       │
│       ├── mtr_data_complete.json  # All data in one file
│       └── mtr_data.db             # SQLite database
│
├── src/
│   ├── __init__.py
│   │
│   ├── crawlers/
│   │   ├── __init__.py
│   │   ├── base_crawler.py         # Base crawler class
│   │   ├── station_crawler.py      # Station data crawler
│   │   ├── exit_crawler.py         # Exit information crawler
│   │   ├── platform_crawler.py     # Platform data crawler
│   │   └── route_crawler.py        # Indoor route data crawler
│   │
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── csv_parser.py           # Parse MTR CSV data
│   │   ├── html_parser.py          # Parse HTML station pages
│   │   └── map_parser.py           # Parse station maps
│   │
│   ├── geocoders/
│   │   ├── __init__.py
│   │   ├── exit_geocoder.py        # Geocode exit locations
│   │   └── platform_geocoder.py    # Geocode platform locations
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── station.py              # Station data model
│   │   ├── exit.py                 # Exit data model
│   │   ├── platform.py             # Platform data model
│   │   ├── route.py                # Route data model
│   │   └── line.py                 # Line data model
│   │
│   ├── exporters/
│   │   ├── __init__.py
│   │   ├── geojson_exporter.py     # Export to GeoJSON
│   │   ├── csv_exporter.py         # Export to CSV
│   │   ├── json_exporter.py        # Export to JSON
│   │   └── sqlite_exporter.py      # Export to SQLite
│   │
│   ├── validators/
│   │   ├── __init__.py
│   │   ├── data_validator.py       # Validate data completeness
│   │   └── geojson_validator.py    # Validate GeoJSON format
│   │
│   └── utils/
│       ├── __init__.py
│       ├── config.py                # Configuration management
│       ├── logger.py                # Logging setup
│       └── rate_limiter.py          # Rate limiting for crawling
│
├── scripts/
│   ├── 01_download_raw_data.py     # Download initial data
│   ├── 02_crawl_stations.py        # Crawl station information
│   ├── 03_crawl_exits.py           # Crawl exit data
│   ├── 04_geocode_locations.py     # Geocode all locations
│   ├── 05_process_routes.py        # Process indoor routes
│   ├── 06_validate_data.py         # Validate all data
│   └── 07_export_all_formats.py    # Export to all formats
│
├── tests/
│   ├── __init__.py
│   ├── test_crawlers.py
│   ├── test_parsers.py
│   ├── test_exporters.py
│   └── test_validators.py
│
├── notebooks/
│   ├── 01_data_exploration.ipynb   # Explore raw data
│   ├── 02_geocoding_analysis.ipynb # Analyze geocoding results
│   └── 03_visualization.ipynb      # Visualize final data
│
└── docs/
    ├── API.md                       # Data format documentation
    ├── CONTRIBUTING.md              # Contribution guidelines
    ├── DATA_SOURCES.md              # Document all data sources
    └── examples/                    # Usage examples
        ├── load_geojson.py
        └── query_walking_times.py
```

## Data Quality & Ethics

### Quality Assurance
- Validate all coordinates are within Hong Kong bounds
- Cross-reference with OpenStreetMap MTR data
- Verify station names match official MTR publications
- Check walking times are reasonable (2-10 minutes typically)
- Ensure all exits link to valid platforms

### Ethical Crawling
- Respect robots.txt
- Implement rate limiting (1-2 requests per second max)
- Cache downloaded pages to avoid repeated requests
- Use official APIs where available
- Provide proper attribution to MTR Corporation
- Release data under public domain (CC0 or similar)

### Data Licensing
- Verify MTR data usage terms
- Document all data sources
- Provide attribution in output files
- Consider CC0, ODbL, or Public Domain dedication

## Future Enhancements

### Additional Data Points
- [ ] Real-time train arrival times
- [ ] Crowd levels at exits/platforms
- [ ] Accessibility features (braille, audio announcements)
- [ ] Exit-to-destination walking times (to nearby landmarks)
- [ ] Multi-language support (add Traditional Chinese)
- [ ] 3D floor level data for multi-level stations

### Integration Opportunities
- [ ] OpenStreetMap import/comparison
- [ ] Transit routing engine integration (OSRM, Valhalla)
- [ ] Mobile app data export
- [ ] Live train tracking integration
- [ ] Wheelchair route optimization

### Data Updates
- [ ] Automated update detection
- [ ] Version control for data changes
- [ ] Historical data preservation
- [ ] Change notification system

## Quick Start (To be implemented)

```bash
# Install dependencies
pip install -r requirements.txt

# Download initial data
python scripts/01_download_raw_data.py

# Run complete crawler
python scripts/02_crawl_stations.py
python scripts/03_crawl_exits.py

# Export data
python scripts/07_export_all_formats.py

# Output will be in data/output/
```

## Contributing
See CONTRIBUTING.md for guidelines on:
- Adding new data sources
- Improving geocoding accuracy
- Adding new export formats
- Data validation improvements

## License
Public Domain / CC0 1.0 Universal
All data collected is for public benefit and open access.

---

**Note**: This is a planning document. Implementation will be done incrementally based on data availability and feasibility.
