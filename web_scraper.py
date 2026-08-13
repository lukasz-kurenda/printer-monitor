# -*- coding: utf-8 -*-
"""Selenium web scraping of printer pages (parallel workers)."""

import logging
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common import WEB_WORKERS_DEFAULT


import re


def _parse_counter_cell(text):
    """Parse a counter cell, tolerating formatting (e.g. '12,345' or '--')."""
    digits = re.sub(r'\D', '', text or '')
    if not digits:
        return None
    return int(digits)


def init_selenium_driver(config):
    """Initialize and return a Selenium Chrome driver instance."""
    try:
        logging.info("Initializing the Selenium driver...")
        chrome_options = Options()
        chrome_options.binary_location = config['WWW']['chrome_binary']
        if config['WWW'].getboolean('headless', fallback=True):
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument('--blink-settings=imagesEnabled=false')
        chrome_options.set_capability('acceptInsecureCerts', True)
        driver = webdriver.Chrome(options=chrome_options)
        logging.info("Selenium driver started.")
        return driver
    except Exception as e:
        logging.error(f"Failed to initialize the Selenium driver: {e}")
        return None


def get_web_data_with_selenium(driver, ip_address):
    """Fetch data over HTTP, using WebDriverWait for greater stability."""
    try:
        logging.info(f"[{ip_address}] Starting web scraping over HTTP...")
        web_data = {'status': 'OK'}
        wait = WebDriverWait(driver, 25)

        # Fetch device information
        driver.get(f"http://{ip_address}/?MAIN=DEVICE")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "TopLevelFrame")))
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "contents")))

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        name_tag = soup.find(id='DeviceName')
        if name_tag:
            web_data['name'] = name_tag.get_text(strip=True)
        location_tag = soup.find(id='DeviceLocation')
        if location_tag:
            web_data['location'] = location_tag.get_text(strip=True)
        driver.switch_to.default_content()

        # Fetch counter information
        driver.get(f"http://{ip_address}/?MAIN=COUNTER&SUB=TOTAL")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "TopLevelFrame")))
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "contents")))

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        color_cell = soup.find('td', id='TotalFullColor')
        if color_cell:
            web_data['color'] = _parse_counter_cell(color_cell.get_text(strip=True))
        bw_cell = soup.find('td', id='TotalBlackColor')
        if bw_cell:
            web_data['bw'] = _parse_counter_cell(bw_cell.get_text(strip=True))
        driver.switch_to.default_content()

        if web_data.get('color') is None or web_data.get('bw') is None:
            logging.warning(f"[{ip_address}] Connected, but no counter elements found on the page.")
            return None

        logging.info(f"[{ip_address}] Web scraping completed successfully.")
        return web_data

    except (TimeoutException, WebDriverException) as e:
        logging.warning(f"[{ip_address}] Web scraping failed: {type(e).__name__}")
        driver.switch_to.default_content()
        return 'offline'
    except Exception as e:
        logging.error(f"[{ip_address}] Unexpected error during web scraping: {e}", exc_info=True)
        driver.switch_to.default_content()
        return None


def scrape_all_with_selenium(ips, config, max_workers=None):
    """Web-scrape multiple printers in parallel (one Chromium driver per thread).

    Returns {ip: result} - result as from get_web_data_with_selenium (dict/'offline'/None).
    """
    if max_workers is None:
        max_workers = config.getint('MONITORING', 'web_workers', fallback=WEB_WORKERS_DEFAULT)
    results = {}

    def _scrape_one(ip):
        try:
            driver = init_selenium_driver(config)
            if not driver:
                logging.error(f"[{ip}] Failed to initialize the Selenium driver.")
                return ip, None
            try:
                return ip, get_web_data_with_selenium(driver, ip)
            finally:
                driver.quit()
        except Exception as e:
            logging.error(f"[{ip}] Unexpected error in web scraper worker: {e}", exc_info=True)
            return ip, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for ip, result in executor.map(_scrape_one, ips):
            results[ip] = result
    return results
