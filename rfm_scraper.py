#!/usr/bin/env python3
import logging
import os
import requests
from configparser import ConfigParser, ExtendedInterpolation
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from bs4 import BeautifulSoup
from pymongo import MongoClient


@dataclass(eq=False, frozen=True)
class Person:
    full_name: str
    is_terr: bool
    birth_date: Optional[date]
    address: Optional[str]
    aliases: Optional[list[str]]
    rfm_id: Optional[int]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Person):
            if self.full_name == other.full_name:
                logger.debug('Comparing persons with same names self: %s and other: %s',
                             self, other)
                if (self.birth_date is not None and
                        other.birth_date is not None):
                    return self.birth_date == other.birth_date
                elif (self.address is not None and
                      other.address is not None):
                    return self.address == other.address
                elif (self.rfm_id is not None
                      and other.rfm_id is not None):
                    return self.rfm_id == other.rfm_id
        return False

    def __hash__(self) -> int:
        return hash(self.full_name)


def parse_person(person: str) -> Person:
    logger.debug('Parsing person string %s', person)
    remainder = person.rstrip('; ')
    id_full_name, _, remainder = remainder.partition(',')
    id_full_name = id_full_name.strip()
    is_terr = id_full_name.endswith('*')
    if is_terr:
        id_full_name = id_full_name[:-1]
    id, _, full_name = id_full_name.partition('. ')
    rfm_id = int(id)
    val, _, remainder = remainder.partition(',')
    val = val.strip()
    if val.startswith('(') and val.endswith(')'):
        aliases = [alias.strip() for alias in val[1:-1].split(';')]
        val, _, remainder = remainder.partition(',')
    else:
        aliases = None
    val = val.strip()
    if val == '':
        birth_date = None
    else:
        try:
            birth_date = datetime.strptime(val, '%d.%m.%Y г.р.')
        except ValueError:
            logger.error('Error to parse date: %s', val)
            birth_date = None

    address = remainder.strip(', ')
    if address == '':
        address = None

    return Person(full_name, is_terr, birth_date, address, aliases, rfm_id)


def scrape_persons() -> Dict[Person, Person]:
    # Parse HTML using BeautifulSoup

    if environment == 'prod' or config['rfm']['use_file'] == 'False':
        siteurl = config['rfm']['url']

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'}
        logger.info('Requesting site url: %s', siteurl)
        response = requests.get(siteurl, headers=headers, verify=False)
        content = response.content
    else:
        filepath = config['rfm']['file_path']
        logger.info('Reading file by path: %s', filepath)
        with open(filepath, 'r') as fp:
            content = fp.read()

    logger.debug('Content of response: %s', content)

    dom = BeautifulSoup(content, 'html.parser')
    rfm_list = dom.select('#russianFL .terrorist-list')[0]
    person_tags = rfm_list.find_all('li')
    logger.info('Found rfm list entities count: %d', len(person_tags))
    scraped_persons = dict()

    for person_tag in person_tags:
        person_str = str(person_tag.string)
        person = parse_person(person_str)
        scraped_persons[person] = person

    logger.info('Parsed persons list length: %d', len(scraped_persons))
    return scraped_persons


def load_db_persons() -> Dict[Person, Person]:
    db_persons = dict()
    for person_json in persons_collection.find():
        person = Person(person_json['fullName'], person_json['isTerr'],
                        person_json['birthDate'], person_json['address'],
                        person_json['aliases'], person_json['rfmId'])
        db_persons[person] = person

    logger.info('Fetched from db persons count: %d', len(db_persons))
    return db_persons


def to_camel_case(val: str) -> str:
    name = ''.join(val.title().split('_'))
    return name[0].lower() + name[1:]


def detect_changes(scraped: Person, db_loaded: Person) -> Dict[str, Any] | None:
    changes = None

    logger.debug('Detecting changes between scraped: %s and db: %s', scraped, db_loaded)
    for attribute, new_value in scraped.__dict__.items():
        old_value = getattr(db_loaded, attribute)

        if (new_value != old_value
                and attribute != 'rfm_id'):
            # Use rfm_id only to detect person, do not keep its value in changes

            if changes is None:
                changes = dict()

            if 'fullName' not in changes:
                changes['fullName'] = scraped.full_name
                changes['isTerr'] = scraped.is_terr
                changes['birthDate'] = scraped.birth_date
                changes['address'] = scraped.address

            old_key = to_camel_case('old_' + attribute)
            new_key = to_camel_case('new_' + attribute)
            changes[old_key] = old_value
            changes[new_key] = new_value

    return changes


def create_event(event: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    changes['action'] = event
    changes['date'] = datetime.now(timezone.utc)
    return changes


environment = os.getenv('PYTHON_ENV', 'dev')

config = ConfigParser(os.environ, interpolation=ExtendedInterpolation())
config.read('config.ini')
config.read(f'config.{environment}.ini')

loglevel = config['log']['level']

# assuming loglevel is bound to the string value obtained from the
# command line argument. Convert to upper case to allow the user to
# specify --log=DEBUG or --log=debug
log_numeric_level = getattr(logging, loglevel.upper(), None)
if not isinstance(log_numeric_level, int):
    raise ValueError('Invalid log level: %s' % loglevel)
logger = logging.getLogger('__name__')
logging.basicConfig(filename='output.log', encoding='utf-8',
                    level=log_numeric_level, format='%(levelname)s: %(asctime)s %(message)s')

mongo = MongoClient(
    host=config['mongodb']['host'],
    username=config['mongodb']['username'],
    password=config['mongodb']['password']
)

persons_collection = mongo[config['mongodb']['rfm_db']][config['mongodb']['persons_collection']]
events_collection = mongo[config['mongodb']['events_db']][config['mongodb']['events_collection']]

scraped_persons = scrape_persons()
db_persons = load_db_persons()

if db_persons:
    # generate changes only after 2nd and consecutive runs to not spam whole list added

    events_list = []

    for db_person in db_persons:
        # loop db_persons, find not present in scrape result and mark as removed

        if db_person not in scraped_persons:
            changes = {to_camel_case(k): v for k, v in db_person.__dict__.items()}
            events_list.append(create_event('removed', changes))

    for scraped_person in scraped_persons:
        # loop scraped_persons, find for new + intersections with db and detect changes

        if scraped_person in db_persons:
            changes = detect_changes(scraped_person, db_persons[scraped_person])
            if changes is not None:
                events_list.append(create_event('changed', changes))
        else:
            changes = {to_camel_case(k): v for k, v in scraped_person.__dict__.items()}
            events_list.append(create_event('added', changes))

    if events_list:
        # save changes list
        events_collection.insert_many(events_list)

if scraped_persons:
    # replace db persons with scraped result

    persons_collection.delete_many({})
    scraped_dcts = list()

    for person in list(scraped_persons.values()):
        dct = {to_camel_case(k): v for k, v in person.__dict__.items()}
        scraped_dcts.append(dct)

    persons_collection.insert_many(scraped_dcts)

mongo.close()
