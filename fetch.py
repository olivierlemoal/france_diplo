#! /usr/bin/env python3

import re
from urllib.parse import urlparse
import os
import logging
import trio
import asks
from tenacity import retry, stop_after_attempt, after_log
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from peewee import IntegrityError
from model import Map, Country, db, DB_FILE

logFormatter = logging.Formatter("%(asctime)s [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()
rootLogger.setLevel(logging.INFO)

fileHandler = logging.FileHandler("fetch.log")
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)

DOWNLOAD_DIR = datetime.now().strftime("%d_%m_%y")
Path(DOWNLOAD_DIR).mkdir(exist_ok=True)

asks.init('trio')
MAX_CONN = 100
session = asks.Session(connections=MAX_CONN)
headers = {'User-Agent': "Mozilla/5.0 (X11; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0"}


async def setup_db():
    r = await get_request("https://www.diplomatie.gouv.fr/fr/conseils-aux-voyageurs/conseils-par-pays-destination/")
    soup = BeautifulSoup(r.text, 'lxml')

    db.connect()
    db.create_tables([Map, Country])
    for country in soup.select('div.clearfix select#recherche_pays option'):
        if country.text == "Sélectionnez un pays/destination":
            continue
        Country.create(country_name=country.text, country_id=country["value"].split("/")[-2], url=country["value"])


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


@retry(stop=stop_after_attempt(3), sleep=trio.sleep, after=after_log(rootLogger, logging.DEBUG))
async def get_request(url, stream=False):
    return await session.get(url, headers=headers, stream=stream)


async def download_map(m):
    DATE_FMT = '%Y%m%d'
    country = m.country_id
    m.date = guess_date(m)
    m.path = DOWNLOAD_DIR + "/" + country + "_" + m.date.strftime(DATE_FMT) + ".jpg"
    logging.info(f"Downloading map for {country} to {m.path}")
    r = await get_request("https://www.diplomatie.gouv.fr/" + m.url, stream=True)
    if r.status_code == 200:
        async with await trio.open_file(m.path, 'wb') as f:
            async for bytechunk in r.body:
                await f.write(bytechunk)


def guess_date(m):
    country = m.country_id
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


async def process_country(country):
    logging.debug(f"Processing country {country.country_name}")
    r = await get_request("https://www.diplomatie.gouv.fr/fr/conseils-aux-voyageurs/conseils-par-pays-destination/" + country.country_id)
    soup = BeautifulSoup(r.text, 'lxml')
    url = find_image(soup)
    if not url:
        logging.info(f"Can't find map URL for country {country.country_name}")
        return
    if Map.select().where((Map.country == country) & (Map.url == url)).exists():
        logging.info(f"No new map for country {country.country_name}")
        return
    try:
        m = Map.create(country=country, url=url)
    except IntegrityError:
        other_country = Map.select().where((Map.url == url)).first().country.country_name
        logging.warning(f"{country.country_name} map already exists ({other_country})")
        return

    if m.url:
        try:
            await download_map(m)
            m.save()
        except Exception as e:
            logging.error(f"Could not download map for {country.country_name} : {e}")
    else:
        logging.error(f"Can't find map for {country.country_name}")


async def main():

    if not os.path.isfile(DB_FILE):
        await setup_db()

    logging.info(f"Processing {Country.select().count()} countries")

    async with trio.open_nursery() as nursery:
        for country in Country.select():
            nursery.start_soon(process_country, country)

trio.run(main)
