#!/usr/bin/env python3
import logging
import os
import requests
from configparser import ConfigParser, ExtendedInterpolation
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, List, Set

from bs4 import BeautifulSoup
from pymongo import MongoClient
from logging import Logger

from pymongo.synchronous.collection import Collection


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


def load_config(env: str) -> ConfigParser:
    cfg = ConfigParser(os.environ, interpolation=ExtendedInterpolation())
    cfg.read('config.ini')
    cfg.read(f'config.{env}.ini')
    return cfg


def configure_logger(cfg: ConfigParser) -> Logger:
    loglevel = cfg['log']['level']
    # assuming loglevel is bound to the string value obtained from the
    # command line argument. Convert to upper case to allow the user to
    # specify --log=DEBUG or --log=debug
    log_numeric_level = getattr(logging, loglevel.upper(), None)

    if not isinstance(log_numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    log = logging.getLogger('__name__')
    logging.basicConfig(filename='output.log', encoding='utf-8',
                        level=log_numeric_level, format='%(levelname)s: %(asctime)s %(message)s')
    return log


def configure_mongo() -> (MongoClient, Collection, Collection):
    client = MongoClient(
        host=config['mongodb']['host'],
        username=config['mongodb']['username'],
        password=config['mongodb']['password']
    )
    persons = client[config['mongodb']['rfm_db']][config['mongodb']['persons_collection']]
    events = client[config['mongodb']['events_db']][config['mongodb']['events_collection']]
    return client, persons, events


def scrape_persons() -> Set[Person]:
    # Parse HTML using BeautifulSoup

    content = load_html()
    # TODO: For remove, because too much data of the page saved in log
    logger.debug('Content of response: %s', content)

    dom = BeautifulSoup(content, 'html.parser')
    rfm_list = dom.select('#russianFL .terrorist-list')[0]
    person_tags = rfm_list.find_all('li')

    logger.info('Found rfm list entities count: %d', len(person_tags))

    persons = set()

    for person_tag in person_tags:
        person_str = str(person_tag.string)
        person = parse_person(person_str)
        persons.add(person)

    logger.info('Parsed persons list length: %d', len(persons))
    return persons


def load_html():
    if environment == 'prod' or not config['rfm'].getboolean('use_file'):
        return scrape_from_site()
    else:
        return load_from_file()


def scrape_from_site() -> bytes:
    site_url = config['rfm']['url']
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/123.0.0.0 Safari/537.36'
    }
    logger.info('Requesting site url: %s', site_url)
    with requests.Session() as session:
        response = session.get(site_url, headers=headers, verify=False)
        content = response.content
    return content


def load_from_file() -> str:
    filepath = config['rfm']['file_path']
    logger.info('Reading file by path: %s', filepath)
    with open(filepath, 'r') as fp:
        content = fp.read()
    return content


def parse_person(person: str) -> Person:
    logger.debug('Parsing person string %s', person)

    remainder = person.rstrip('; ')

    id_fullname, _, remainder = remainder.partition(',')
    id_fullname = id_fullname.strip()

    is_terr = id_fullname.endswith('*')
    if is_terr:
        id_fullname = id_fullname[:-1]

    rfm_id_str, _, full_name = id_fullname.partition('. ')
    rfm_id = int(rfm_id_str)

    aliases_or_birth_date, _, remainder = remainder.partition(',')
    aliases_or_birth_date = aliases_or_birth_date.strip()
    if aliases_or_birth_date.startswith('(') and aliases_or_birth_date.endswith(')'):
        aliases = [alias.strip() for alias in aliases_or_birth_date[1:-1].split(';')]
        birth_date_str, _, remainder = remainder.partition(',')
    else:
        aliases = None
        birth_date_str = aliases_or_birth_date

    birth_date_str = birth_date_str.strip()
    if birth_date_str == '':
        birth_date = None
    else:
        try:
            birth_date = datetime.strptime(birth_date_str, '%d.%m.%Y г.р.')
        except ValueError:
            logger.error('Error to parse date: %s', birth_date_str)
            birth_date = None

    address = remainder.strip(', ')
    if address == '':
        address = None

    return Person(full_name, is_terr, birth_date, address, aliases, rfm_id)


def load_db_persons() -> Dict[Person, Person]:
    try:
        persons = dict()
        for person_json in persons_collection.find():
            person = Person(person_json['fullName'], person_json['isTerr'],
                            person_json['birthDate'], person_json['address'],
                            person_json['aliases'], person_json['rfmId'])
            persons[person] = person

        logger.info('Fetched from db persons count: %d', len(persons))
        return persons
    except BaseException as e:
        logger.error("Mongo reading error %s", e)
        mongo.close()
        raise e


def save_list_changes():
    try:
        if db_persons:
            # check if rfmDb.persons already has entries because we
            # generate changes only after 2nd and consecutive runs to
            # not spam whole rfm persons list added events

            events_list = generate_rfm_list_changes()

            if events_list:
                events_collection.insert_many(events_list)

        if scraped_persons:
            # replace rfmDb.persons with actual scraped result

            persons_collection.delete_many({})
            scraped_person_dictionaries = convert_to_dictionaries(scraped_persons)
            persons_collection.insert_many(scraped_person_dictionaries)
    finally:
        mongo.close()


def generate_rfm_list_changes() -> List[Dict[str, Any]]:
    events_list = []

    for db_person in db_persons:
        # loop db_persons, find not present in scrape result and mark as removed

        if db_person not in scraped_persons:
            add_whole_person_change('removed', db_person, events_list)

    for scraped_person in scraped_persons:
        # loop scraped_persons, find for intersections with db and detect changes + newly added

        if scraped_person in db_persons:
            changes = detect_changes(scraped_person, db_persons[scraped_person])
            if changes is not None:
                events_list.append(create_event('changed', changes))
        else:
            add_whole_person_change('added', scraped_person, events_list)

    return events_list


def add_whole_person_change(event_name: str, person: Person, events_list: List[Dict[str, Any]]):
    changes = {to_camel_case(k): v for k, v in person.__dict__.items()}
    events_list.append(create_event(event_name, changes))


def to_camel_case(val: str) -> str:
    name = ''.join(val.title().split('_'))
    return name[0].lower() + name[1:]


def create_event(event: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    changes['action'] = event
    changes['date'] = datetime.now(timezone.utc)
    return changes


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


def convert_to_dictionaries(persons: Set[Person]) -> List[Dict[str, Any]]:
    scraped_dictionaries = list()
    for person in persons:
        dct = {to_camel_case(k): v for k, v in person.__dict__.items()}
        scraped_dictionaries.append(dct)
    return scraped_dictionaries


environment = os.getenv('PYTHON_ENV', 'dev')
config = load_config(environment)
logger = configure_logger(config)
mongo, persons_collection, events_collection = configure_mongo()

scraped_persons = scrape_persons()
db_persons = load_db_persons()

save_list_changes()
