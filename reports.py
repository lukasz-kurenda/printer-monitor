# -*- coding: utf-8 -*-
"""HTML and Excel report generation."""

import html
import logging
import os

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


def create_excel_report(report_data, filename):
    if not PANDAS_AVAILABLE:
        return None
    df_data = []
    # Filtering removed - now all data goes into the report
    for d in report_data:
        df_data.append({
            'IP address': d.get('ip'),
            'Location': d.get('location'),
            'Name': d.get('name'),
            'Model': d.get('model'),
            'Color counter': d.get('color'),
            'B&W counter': d.get('bw'),
            'Total': d.get('sum'),
            'Notes': d.get('comment', '')  # New column for notes
        })
    df = pd.DataFrame(df_data)
    # Define the column order
    df = df[['IP address', 'Location', 'Name', 'Model', 'Color counter', 'B&W counter', 'Total', 'Notes']]
    df.to_excel(filename, index=False, engine='openpyxl')
    logging.info(f"Excel report saved to: {filename}")
    return filename


def _esc(value):
    """HTML escaping for device-provided data (W6)."""
    return html.escape(str(value if value is not None else ''))


def create_html_report(report_data, today_str, report_type="Toner", alert_level="low"):
    is_toner_report = report_type == "Toner"

    # ... (start of the function unchanged)
    if is_toner_report:
        if alert_level == 'critical':
            title = "URGENT: Critical toner level"
            message = "<p style='text-align:center; font-size:14px;'>The following consumables require <b>immediate replacement</b>!</p>"
        else:  # low
            title = "WARNING: Low toner level"
            message = "<p style='text-align:center; font-size:14px;'>Please check the stock levels and order the listed consumables.</p>"
    else:
        title = "Printer counter report"
        message = ""

    html = f"""
    <html><head><style>
        body{{font-family:Arial,sans-serif;margin:20px}}
        table{{border-collapse:collapse;width:95%;margin:auto}}
        th,td{{border:1px solid #cccccc;text-align:left;padding:10px;font-size:12px}}
        th{{background-color:#eeeeee;font-weight:bold}}
        tr.low{{background-color:#fff9c4;}}
        tr.critical{{background-color:#b71c1c; color: white; font-weight: bold;}}
        tr.summary{{font-weight:bold;background-color:#f0f0f0;}}
        tr.history td {{ background-color: #f5f5f5; color: #555; font-style: italic; }}
        tr.offline-error td {{
            color: #d9534f;
            font-weight: bold;
            text-transform: uppercase;
            text-align: center;
            background-color: #f2dede;
        }}
        h2{{text-align:center}}
    </style></head><body>
    <h2>{title} for {today_str}</h2>
    {message}
    <table><tr>
    """

    headers = ['IP', 'Location', 'Name', 'Model', 'Toner name', 'Level %'] if is_toner_report else ['IP', 'Location', 'Name', 'Model', 'Color', 'B&W', 'Total', 'Notes']
    for header in headers:
        html += f"<th>{header}</th>"
    html += "</tr>"
    total_color, total_bw, total_sum = 0, 0, 0

    for data in report_data:
        if is_toner_report:
            row_class = alert_level
        else:
            status = data.get('status', '')
            if status == 'HISTORY':
                row_class = 'history'
            elif status in ['OFFLINE', 'ERROR']:
                row_class = 'offline-error'
            else:
                row_class = ''

        html += f"<tr class='{row_class}'>"

        if is_toner_report:
            html += (f"<td>{_esc(data.get('ip', ''))}</td>"
                     f"<td>{_esc(data.get('location', ''))}</td>"
                     f"<td>{_esc(data.get('name', ''))}</td>"
                     f"<td>{_esc(data.get('model', ''))}</td>"
                     f"<td>{_esc(data.get('desc', ''))}</td>"
                     f"<td><b>{data.get('level', 0.0):.1f}%</b></td>")
        else:
            if data.get('status') in ['OFFLINE', 'ERROR']:
                html += (f"<td class='offline-error' colspan='{len(headers)}'>"
                         f"Printer {_esc(data.get('ip'))} - {_esc(data.get('name'))} "
                         f"({_esc(data.get('comment', ''))})</td>")
            else:
                html += (f"<td>{_esc(data.get('ip', ''))}</td>"
                         f"<td>{_esc(data.get('location', 'Brak'))}</td>"
                         f"<td>{_esc(data.get('name', 'Brak'))}</td>"
                         f"<td>{_esc(data.get('model', 'Brak'))}</td>"
                         f"<td>{_esc(data.get('color', 'N/A'))}</td>"
                         f"<td>{_esc(data.get('bw', 'N/A'))}</td>"
                         f"<td>{_esc(data.get('sum', 'N/A'))}</td>"
                         f"<td>{_esc(data.get('comment', ''))}</td>")
                if isinstance(data.get('color'), int):
                    total_color += data.get('color', 0)
                if isinstance(data.get('bw'), int):
                    total_bw += data.get('bw', 0)
                if isinstance(data.get('sum'), int):
                    total_sum += data.get('sum', 0)
        html += "</tr>"
    if not is_toner_report:
        html += f"<tr class='summary'><td colspan='4' style='text-align:right;'>TOTAL:</td><td>{total_color}</td><td>{total_bw}</td><td>{total_sum}</td><td></td></tr>"
    html += "</table></body></html>"
    return html
