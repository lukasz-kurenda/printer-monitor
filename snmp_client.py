# -*- coding: utf-8 -*-
"""SNMP reads: toner levels, page counters, device info (pysnmp 7)."""

import asyncio
import logging

from pysnmp.error import PySnmpError  # noqa: F401  (kept for API compatibility)
from pysnmp.hlapi.asyncio import (CommunityData, ContextData, ObjectIdentity,
                                  ObjectType, SnmpEngine, UdpTransportTarget,
                                  get_cmd, next_cmd)

from printers import get_custom_oids_for_ip


async def get_snmp_data_async(ip, oids, community, timeout=5, retries=1, port=161):
    oids = [oid for oid in oids if oid]
    if not oids:
        return {}

    snmp_engine = SnmpEngine()
    transport_target = await UdpTransportTarget.create((ip, port), timeout=timeout, retries=retries)
    results = {}

    try:
        object_types = [ObjectType(ObjectIdentity(oid)) for oid in oids]
        error_indication, error_status, error_index, var_binds = await get_cmd(
            snmp_engine, CommunityData(community), transport_target, ContextData(), *object_types
        )
        if error_indication:
            logging.debug(f"[{ip}] SNMP error (get_cmd): {error_indication}")
        elif error_status:
            logging.debug(f"[{ip}] SNMP status error (get_cmd): {error_status.prettyPrint()}")
            for var_oid, val in var_binds:
                if 'noSuch' not in str(val):
                    results[str(var_oid)] = str(val)
        else:
            for var_oid, val in var_binds:
                results[str(var_oid)] = str(val)
    except Exception as e:
        logging.error(f"[{ip}] Wyjatek w get_snmp_data_async: {e}")
    return results


async def get_printer_base_info(ip, community, timeout=5, retries=1, port=161):
    oids = ['1.3.6.1.2.1.25.3.2.1.3.1', '1.3.6.1.2.1.1.5.0', '1.3.6.1.2.1.1.6.0']
    data = await get_snmp_data_async(ip, oids, community, timeout=timeout, retries=retries, port=port)
    model = data.get('1.3.6.1.2.1.25.3.2.1.3.1', "Not read")
    name = data.get('1.3.6.1.2.1.1.5.0', "None")
    location = data.get('1.3.6.1.2.1.1.6.0', "None")
    return {'model': model, 'name': name, 'location': location}


async def walk_snmp_oid(ip, community, oid, timeout=10, retries=2, port=161):
    results = {}
    snmp_engine = SnmpEngine()
    transport_target = await UdpTransportTarget.create((ip, port), timeout=timeout, retries=retries)
    var_binds = [ObjectType(ObjectIdentity(oid))]
    while True:
        try:
            error_indication, error_status, error_index, var_bind_table = await next_cmd(
                snmp_engine, CommunityData(community), transport_target, ContextData(), *var_binds
            )
            if error_indication or error_status:
                break
            var_binds = var_bind_table[0]
            current_oid, current_val = var_binds
            if not str(current_oid).startswith(oid):
                break
            index = str(current_oid).replace(f"{oid}.", '')
            results[index] = str(current_val)
            var_binds = [var_binds]
        except Exception as e:
            logging.error(f"[{ip}] Error during SNMP 'walk' for OID {oid}: {e}")
            break
    return results


async def get_toner_levels_snmp(ip, community, config, custom_oids=None):
    """
    Fetch toner levels for a printer, optimizing the number of SNMP requests.
    1. Discover all consumables via an SNMP walk.
    2. Collect OIDs for current and maximum levels of all consumables.
    3. Send a single bulk SNMP get to fetch all data at once.
    4. Process the results and return a list of toners with their levels.
    """
    toners = []
    oid_map = custom_oids if custom_oids and custom_oids.get('desc') else {
        'desc': '1.3.6.1.2.1.43.11.1.1.6',
        'max': '1.3.6.1.2.1.43.11.1.1.8',
        'current': '1.3.6.1.2.1.43.11.1.1.9',
        'value_is_percentage': 'false'
    }
    low_status_percent = config.getint('MONITORING', 'toner_low_status_percent', fallback=3)
    snmp_timeout = config.getint('MONITORING', 'snmp_timeout', fallback=5)
    snmp_retries = config.getint('MONITORING', 'snmp_retries', fallback=2)
    snmp_port = config.getint('MONITORING', 'snmp_port', fallback=161)
    base_desc_oid = oid_map.get('desc')
    if not base_desc_oid:
        return []

    # 1. Discover consumables via an SNMP walk
    discovered_supplies = await walk_snmp_oid(ip, community, base_desc_oid,
                                              timeout=snmp_timeout, retries=snmp_retries,
                                              port=snmp_port)
    if not discovered_supplies:
        logging.warning(f"[{ip}] No consumables found by 'walk' for OID: {base_desc_oid}")
        return []

    # 2. Prepare OID lists for the bulk request
    oids_to_fetch = []
    supply_details = {}
    value_is_percentage = oid_map.get('value_is_percentage', 'false').lower() == 'true'

    for index, desc in discovered_supplies.items():
        current_oid = f"{oid_map.get('current')}.{index}"
        oids_to_fetch.append(current_oid)

        max_oid = None
        if not value_is_percentage:
            max_oid = f"{oid_map.get('max')}.{index}"
            oids_to_fetch.append(max_oid)

        supply_details[index] = {'desc': desc, 'current_oid': current_oid, 'max_oid': max_oid}

    # 3. Send a single bulk SNMP request
    logging.info(f"[{ip}] Fetching {len(oids_to_fetch)} OIDs for {len(discovered_supplies)} consumables...")
    all_levels_data = await get_snmp_data_async(ip, oids_to_fetch, community,
                                                timeout=snmp_timeout, retries=snmp_retries,
                                                port=snmp_port)

    # 4. Process the received data
    for index, details in supply_details.items():
        try:
            desc = details['desc']
            current_oid = details['current_oid']
            current_level_str = all_levels_data.get(current_oid)

            if current_level_str is None or current_level_str == '':
                logging.warning(f"[{ip}] Empty value received for '{desc}'. Skipping.")
                continue

            current_level = int(current_level_str)
            toner_data = {'desc': desc, 'raw_current': current_level, 'status': 'normal'}

            if value_is_percentage:
                toner_data.update({'level': float(current_level), 'raw_max': 100})
            else:
                max_oid = details['max_oid']
                max_level_str = all_levels_data.get(max_oid)

                if max_level_str is None or max_level_str == '':
                    continue
                max_level = int(max_level_str)
                toner_data['raw_max'] = max_level

                if current_level == -3:
                    toner_data.update({'level': float(low_status_percent), 'status': 'low'})
                elif max_level == -2:
                    toner_data.update({'level': 100.0, 'status': 'new'})
                elif max_level > 0 and current_level >= 0:
                    toner_data['level'] = min((current_level / max_level) * 100, 100.0)
                else:
                    continue  # Skip if the data is invalid

            toners.append(toner_data)
        except (ValueError, TypeError, ZeroDivisionError) as e:
            logging.warning(f"[{ip}] Cannot process data for '{details['desc']}'. Error: {e}")
            continue

    logging.info(f"[{ip}] Processed data for {len(toners)} toners.")
    return toners


async def get_counters_snmp(ip, community, custom_oids=None,
                            timeout=5, retries=1, port=161):
    """
    Reads page counters over SNMP.
    If custom OIDs are defined for counters, they are used.
    Otherwise, a generic total-pages OID is used as a fallback.
    """
    if custom_oids and custom_oids.get('oid_color_count') and custom_oids.get('oid_bw_count'):
        logging.info(f"[{ip}] Using custom OIDs to read page counters.")
        color_oid = custom_oids.get('oid_color_count')
        bw_oid = custom_oids.get('oid_bw_count')
        data = await get_snmp_data_async(ip, [color_oid, bw_oid], community,
                                         timeout=timeout, retries=retries, port=port)

        color_count_str = data.get(color_oid)
        bw_count_str = data.get(bw_oid)

        try:
            if color_count_str is None and bw_count_str is None:
                logging.warning(f"[{ip}] Custom counter OIDs returned no values.")
                return None

            color_count = int(color_count_str) if color_count_str is not None else 0
            bw_count = int(bw_count_str) if bw_count_str is not None else 0
            return {'color': color_count, 'bw': bw_count, 'sum': color_count + bw_count, 'status': 'OK'}
        except (ValueError, TypeError) as e:
            logging.warning(f"[{ip}] Failed to process custom SNMP counter values. Check the OIDs. Error: {e}")
            return None

    logging.info(f"[{ip}] Using the generic SNMP method to read the total counter (fallback).")
    total_oid = '1.3.6.1.2.1.43.10.2.1.4.1.1'
    total_data = await get_snmp_data_async(ip, [total_oid], community,
                                           timeout=timeout, retries=retries, port=port)
    total_count = total_data.get(total_oid)
    if total_count:
        try:
            total = int(total_count)
            # Assume the total is black & white if color is not specified
            return {'color': 0, 'bw': total, 'sum': total, 'status': 'OK'}
        except (ValueError, TypeError):
            logging.warning(f"[{ip}] Failed to process the SNMP total counter.")
    return None
