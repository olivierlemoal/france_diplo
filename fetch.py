#! /usr/bin/env python3

import re
from urllib.parse import urlparse
import os
import logging
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from peewee import *

DB_FILE = 'maps.db'
db = SqliteDatabase(DB_FILE)
logging.basicConfig(level=logging.INFO)
DOWNLOAD_DIR = datetime.now().strftime("%d_%m_%y")
Path(DOWNLOAD_DIR).mkdir(exist_ok=True)

class BaseModel(Model):
    class Meta:
        database = db

class Country(BaseModel):
    country_id = CharField(primary_key=True)
    country_name = CharField()
    url = CharField()

class Map(BaseModel):
    country = ForeignKeyField(Country, backref="maps")
    filename = CharField(null=True, unique=True)
    url = CharField(null=True, unique=True, index=True)
    date = DateTimeField(null=True)

headers = {'User-Agent': "Mozilla/5.0 (X11; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0"}

def setup_db():
    db.connect()
    db.create_tables([Map, Country])

    r = requests.get("https://www.diplomatie.gouv.fr/fr/conseils-aux-voyageurs/conseils-par-pays-destination/", headers=headers)
    soup = BeautifulSoup(r.text, 'lxml')
    for country in soup.select('div.clearfix select#recherche_pays option'):
        if country.text == "Sélectionnez un pays/destination":
            continue
        Country.create(country_name=country.text, country_id=country["value"].split("/")[-2], url=country["value"])


if not os.path.isfile(DB_FILE): 
    setup_db()

def find_image(soup):
    # Most of URLs
    select = soup.select('dl.spip_documents')
    url = None
    if select:
        url = select[0].img["src"]
    # Afghanistan
    select = soup.select('a.spip_in.mediabox')
    if select:
        url = select[0]["href"]
    # Afrique du Sud
    select = soup.select('figure.spip_documents')
    if select:
        url = select[0].img["src"]
    # remove extra "?""
    if not url:
        return
    url = urlparse(url)
    return url.netloc + url.path

def download_map(m):
    DATE_FMT = '%Y%m%d'
    country = m.country_id
    m.date = guess_date(m)
    m.filename = country + "_" + m.date.strftime(DATE_FMT) + ".jpg"
    logging.info("Downloading map for {} as {}".format(country, m.filename))
    r = requests.get("https://www.diplomatie.gouv.fr/" + m.url, headers=headers)
    if r.status_code == 200:
        with open(DOWNLOAD_DIR + "/" + m.filename, 'wb') as f:
            for chunk in r:
                f.write(chunk)

def guess_date(m):
    filename = os.path.basename(urlparse(m.url).path)
    date = re.findall(r".*(\d\d\d\d\d\d\d\d).*", filename)
    if date:
        if int(date[0][0:4]) < 2013:
            # more likely %d%m%Y than %Y%m%d
            date = datetime.strptime(date[0], '%d%m%Y')
        else:
            date = datetime.strptime(date[0], '%Y%m%d')
        return date
    date = re.findall(r".*(\d\d-\d\d-\d\d\d\d).*", filename)
    if date:
        date = datetime.strptime(date[0], '%d-%m-%Y')
        return date
    date = re.findall(r".*(\d\d-\d\d-\d\d).*", filename)
    if date:
        date = datetime.strptime(date[0], '%d-%m-%y')
        return date
    logging.warning(f"Can't find date for {country} (filename {filename}), using today's date.")
    date = datetime.now()
    return date


logging.info(f"Processing {Country.select().count()} countries")
for country in Country.select():
    logging.debug(f"Processing country {country.country_name}")
    r = requests.get("https://www.diplomatie.gouv.fr/fr/conseils-aux-voyageurs/conseils-par-pays-destination/" + country.country_id, headers=headers)
    soup = BeautifulSoup(r.text, 'lxml')
    url = find_image(soup)
    if not url:
        logging.info(f"Can't find map URL for country {country.country_name}")
        continue
    if Map.select().where((Map.country == country) & (Map.url == url)).exists():
        logging.info(f"No new map for country {country.country_name}")
        continue
    try:
        m = Map.create(country=country, url=url)
    except IntegrityError:
        other_country = Map.select().where((Map.url == url)).first().country.country_name
        logging.warning(f"{country.country_name} map already exists ({other_country})")
        continue

    if m.url:
        download_map(m)
    else:
        logging.error(f"Can't find map for {country.country_name}")
    m.save()