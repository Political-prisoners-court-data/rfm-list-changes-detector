# Web scipt for detecting changes in fedsfm.ru (RFM, RosFinMonitoring) private persons list

## Prerequisites

1. Python 3
2. Reproduce the environment with requirements.txt
3. To start, run the following command:

```bash
python3 rfm_scraper.py
```

## Configuration

1. Script is configurable throught layered config.ini, config.dev.ini and config.prod.ini configuration files.

2. By default dev environment is used and script is parsing local fedsfm_lists.html file.

3. To change environment and start to make request to the original site, either set $ENVIRONMENT variable or change property 'fsm.use_file' to False in config.dev.ini file.

4. Database connection is also configurable through config.ini files.
