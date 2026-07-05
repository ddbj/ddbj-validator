import re
import logging
from dateutil import parser, tz

logger = logging.getLogger(__name__)

_INSDC_DATE_PATTERN = re.compile(r"^(?:\d{4}(?:-\d{2}(?:-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?)?)?|(?:\d{2}-)?[A-Za-z]{3}-\d{4})(?:/(?:\d{4}(?:-\d{2}(?:-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?)?)?|(?:\d{2}-)?[A-Za-z]{3}-\d{4}))?$")
# INSDC collection_date 形式パターン（ddbj definitions.json の format_pattern と同一）。
# ddbj/biosample 共有の公開定数（biosample R0007/R0136 が ddbj と同じ判定を使うため）。
INSDC_DATE_PATTERN = _INSDC_DATE_PATTERN
_LATLON_DMS_PATTERN = re.compile(r"^(?P<lat_deg>\d{1,2})\D+(?P<lat_min>\d{1,2})\D+(?P<lat_sec>\d{1,2}(?:\.\d+)?)\D+(?P<lat_hemi>[NS])[ ,_;]+(?P<lng_deg>\d{1,3})\D+(?P<lng_min>\d{1,2})\D+(?P<lng_sec>\d{1,2}(?:\.\d+)?)\D+(?P<lng_hemi>[EW])$")
_LATLON_DEC_INSDC_PATTERN = re.compile(r"^(?P<lat_dec>\d{1,2}(?:\.\d+)?)\s*(?P<lat_dec_hemi>[NS])[ ,_;]+(?P<lng_dec>\d{1,3}(?:\.\d+)?)\s*(?P<lng_dec_hemi>[EW])$")
_LATLON_DEC_REVERSED_PATTERN = re.compile(r"^(?P<lat_dec_hemi>[NS])\s*(?P<lat_dec>\d{1,2}(?:\.\d+)?)[ ,_;]+(?P<lng_dec_hemi>[EW])\s*(?P<lng_dec>\d{1,3}(?:\.\d+)?)$")
_LATLON_DEC_SIGNED_PATTERN = re.compile(r"^(?P<lat_dec>-*\d{1,2}(?:\.\d+))[^\d-]+(?P<lng_dec>-*\d{1,3}(?:\.\d+))$")
_LATLON_DEC_DETAIL_PATTERN = re.compile(r"^(?P<lat_dec>\d{1,2}\.)(?P<lat_dec_point>\d+)\s*(?P<lat_dec_hemi>[NS])[ ,_;]+(?P<lng_dec>\d{1,3}\.)(?P<lng_dec_point>\d+)\s*(?P<lng_dec_hemi>[EW])$")

def _parse_and_format_date(val):
    """日付を解釈し、入力の粒度(年、年月、年月日)に合わせてINSDC推奨のフォーマットに直す。

    保守方針: 入力に 4 桁の年が無い（例 "Dec-16" のような 2 桁年）場合は年を推測できず、
    誤った autofix（"Dec-16" を当年の 12/16 とする等）を生むため **補正しない**（ddbj/biosample 共通）。
    公的 DB では誤補正を避けるのが正しい。→ 呼び出し側では invalid（未補正）として扱われる。
    """
    if not re.search(r'\d{4}', val):
        return None, None
    try:
        val_clean = re.sub(r'[\s/.,]+', '-', val.strip())
        dt = parser.parse(val_clean)
        
        if dt.tzinfo:
            dt = dt.astimezone(tz.UTC)
            
        digits = re.findall(r'\d+', val)
        has_time = 'T' in val.upper() or ':' in val
        has_month_word = re.search(r'[A-Za-z]{3,}', val)
        
        if has_time:
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), dt
            
        comp_count = len(digits) + (1 if has_month_word else 0)
        if comp_count == 1:
            return dt.strftime("%Y"), dt
        elif comp_count == 2:
            return dt.strftime("%Y-%m"), dt
        else:
            return dt.strftime("%Y-%m-%d"), dt
    except Exception as e:
        logger.debug(f"Failed to parse date '{val}': {e}", exc_info=True)
        return None, None

def fix_insdc_date(val):
    """単一または範囲の日付をINSDC形式に補正する"""
    val = str(val).strip()
    if not val: return val
        
    if '/' in val:
        parts = [p.strip() for p in val.split('/')]
        if len(parts) == 2:
            start_str, start_dt = _parse_and_format_date(parts[0])
            end_str, end_dt = _parse_and_format_date(parts[1])
            
            if start_str and end_str:
                if start_dt and end_dt and start_dt > end_dt:
                    return f"{end_str}/{start_str}"
                return f"{start_str}/{end_str}"
    
    fixed_str, _ = _parse_and_format_date(val)
    if fixed_str:
        return fixed_str
        
    return val

def fix_insdc_lat_lon(val):
    """lat_lonのテキストをINSDCフォーマットに補正する"""
    if not val: return None
    lat_lon = str(val).strip()
    insdc_latlon = None

    m_dms = _LATLON_DMS_PATTERN.match(lat_lon)
    m_dec_insdc = _LATLON_DEC_INSDC_PATTERN.match(lat_lon)
    m_dec_rev = _LATLON_DEC_REVERSED_PATTERN.match(lat_lon)
    m_dec_signed = _LATLON_DEC_SIGNED_PATTERN.match(lat_lon)

    if m_dms:
        d = m_dms.groupdict()
        lat = round(int(d['lat_deg']) + float(d['lat_min'])/60.0 + float(d['lat_sec'])/3600.0, 4)
        lng = round(int(d['lng_deg']) + float(d['lng_min'])/60.0 + float(d['lng_sec'])/3600.0, 4)
        insdc_latlon = f"{lat} {d['lat_hemi']} {lng} {d['lng_hemi']}"
        
    elif m_dec_insdc:
        d = m_dec_insdc.groupdict()
        insdc_latlon = f"{d['lat_dec']} {d['lat_dec_hemi']} {d['lng_dec']} {d['lng_dec_hemi']}"
        
    elif m_dec_rev:
        d = m_dec_rev.groupdict()
        insdc_latlon = f"{d['lat_dec']} {d['lat_dec_hemi']} {d['lng_dec']} {d['lng_dec_hemi']}"
        
    elif m_dec_signed:
        d = m_dec_signed.groupdict()
        lat_val, lng_val = d['lat_dec'], d['lng_dec']
        lat_hemi = "S" if lat_val.startswith("-") else "N"
        lng_hemi = "W" if lng_val.startswith("-") else "E"
        lat_dec, lng_dec = lat_val.lstrip("-"), lng_val.lstrip("-")
        insdc_latlon = f"{lat_dec} {lat_hemi} {lng_dec} {lng_hemi}"

    if not insdc_latlon:
        return None

    # 小数点8桁までに切り捨て
    m_detail = _LATLON_DEC_DETAIL_PATTERN.match(insdc_latlon)
    if m_detail:
        d = m_detail.groupdict()
        lat_point = d['lat_dec_point'][:8]
        lng_point = d['lng_dec_point'][:8]
        insdc_latlon = f"{d['lat_dec']}{lat_point} {d['lat_dec_hemi']} {d['lng_dec']}{lng_point} {d['lng_dec_hemi']}"

    return insdc_latlon