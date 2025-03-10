# Web scipt for detecting changes in fedsfm.ru (RFM, RosFinMonitoring) private persons list

[![Deploy rfm-scraper-script](https://github.com/Political-prisoners-court-data/rfm-list-changes-detector/actions/workflows/cicd.yml/badge.svg?branch=main)](https://github.com/Political-prisoners-court-data/rfm-list-changes-detector/actions/workflows/cicd.yml)

## Description

Based on following algorithm:

1. Scrape new list from site
2. Detect changes between previous snapshot of a list in a database and a currently scraped list. 
3. Save detected changes in a list
4. Save actual list of persons in database

## Prerequisites

1. Python 3.12
2. Reproduce the environment with requirements.txt (for example with venv)
```Bash
python -m venv .venv
```
```
source .venv/bin/activate
```
```
pip install -r requirements.txt
```
3. To start, run the following command:

```bash
python3 rfm_scraper.py
```
4. Script log is available in `./output.log`

## Configuration

1. Script is configurable through layered `config.ini`, `config.dev.ini` and `config.prod.ini` configuration files.

2. By default `dev` environment is used and script is parsing local `fedsfm_lists.html` file.

3. To change environment and start to make request to the original site, either set `$ENVIRONMENT` variable or change property `fsm.use_file` to `False` in `config.dev.ini` file.

4. A MongoDB connection is also configurable through `config.ini` files.
