"""Extract hourly directional volumes from Imperial PDF reports (Python 3.12).

Requires pdfplumber: python -m pip install pdfplumber
Reads PDFs recursively; excludes VOID folders. Source files are never changed.
Supported layouts: weekly 60 Min Volume; Full Length 60 Minute lane reports.
Peak tables and average columns are excluded. Unsupported layouts are logged.
Outputs CSV files for Access import, not direct database writes.
"""
from __future__ import annotations
import argparse
import csv
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

SOURCE = Path(r'C:\Users\Kschellinger\SJTPO_Git\TAZ_Modular\input\02_May ATRs')
OUTPUT = Path(r'C:\Users\Kschellinger\SJTPO_Git\TAZ_Modular\traffic_counts\processed')
TARGET = re.compile(r'_60\s*Min(?:ute)?(?:\s*Volume)?(?:\s*\(\d+\))?\.pdf$', re.I)
DIRECTIONS = {'northbound':'NB','southbound':'SB','eastbound':'EB','westbound':'WB'}

def number(s):
    if s in ('*','-',''): return None
    if not re.fullmatch(r'\d+(?:,\d{3})*',s):
        raise ValueError(f'Invalid count: {s!r}')
    return int(s.replace(',',''))

def extract(path):
    import pdfplumber
    records, local = [], {}
    station_match = re.search(r'\bATR\s*(\d+)',path.name,re.I)
    if not station_match:
        station_match = re.match(r'^(\d+)\s*[.\-_]',path.name)
    if not station_match:
        station_match = next((m for part in reversed(path.parts[:-1]) if (m:=re.fullmatch(r'(\d+)_[VRT]',part,re.I))),None)
    if not station_match: raise ValueError('Cannot identify ATR station number')
    station='ATR '+station_match[1]
    description=TARGET.sub('',path.name)
    def add(day,hour,direction,value,page):
        key=(station,day,hour,direction)
        if key in local: raise ValueError(f'Duplicate timestamp within PDF: {key}')
        local[key]=value
        records.append(dict(StationID=station,CountDate=day.strftime('%m/%d/%Y'),
                            HourStart=f'{hour:02d}:00',Direction=direction,Volume=value,
                            Description=description,SourcePage=page))
    with pdfplumber.open(path) as pdf:
        texts=[p.dedupe_chars().extract_text() or '' for p in pdf.pages]
    if not any(t.strip() for t in texts): raise ValueError('No extractable PDF text; OCR required')
    first=texts[0]
    if re.search(r'^Time Mon Tue Wed Thu Fri Sat Sun Mon - Fri Mon - Sun$',first,re.M):
        for page,text in enumerate(texts,1):
            week=re.search(r'^(\d{1,2}/\d{1,2}/\d{4})\s+.*Average$',text,re.M)
            if not week: raise ValueError(f'Page {page}: missing weekly date header')
            monday=datetime.strptime(week[1],'%m/%d/%Y').date()
            if monday.weekday()!=0: raise ValueError('Weekly anchor is not Monday')
            columns=[[] for _ in range(7)]; hours=0
            for line in text.splitlines():
                m=re.match(r'^\s*(\d{1,2}):00\s*(AM|PM)?\s+(.+)$',line)
                if not m: continue
                if hours>=24 or int(m[1])!=(hours%12 or 12) or (m[2] and m[2]!=('AM' if hours<12 else 'PM')):
                    raise ValueError('Unexpected weekly time sequence')
                values=m[3].split()
                if len(values)!=9: raise ValueError('Expected seven day columns and two average columns')
                for col in range(7):
                    value=number(values[col]);columns[col].append(value)
                    add(monday+timedelta(days=col),hours,'UNKNOWN',value,page)
                hours+=1
            if hours==0: continue  # Empty trailing calendar page.
            if hours!=24: raise ValueError('Incomplete weekly table layout')
            total=re.search(r'^Total\s+(.+)$',text,re.M)
            if not total or len(total[1].split())!=9: raise ValueError('Missing weekly totals')
            totals=[number(v) for v in total[1].split()]
            for col in range(7):
                if any(v is not None for v in columns[col]) and sum(v or 0 for v in columns[col])!=totals[col]:
                    raise ValueError('Hourly sum differs from weekly printed total')
    elif re.search(r'Weekday\s+Average',first):
        for page,text in enumerate(texts,1):
            week=re.search(r'^(\d{1,2}/\d{1,2}/\d{4})\s+Monday\s+Tuesday\s+Wednesday\s+Thursday\s+Friday\s+Weekday Average\s+Saturday\s+Sunday\s*$',text,re.M)
            if not week: raise ValueError(f'Page {page}: unrecognized weekly header')
            monday=datetime.strptime(week[1],'%m/%d/%Y').date()
            if monday.weekday()!=0: raise ValueError('Weekly anchor is not Monday')
            headers=re.search(r'^Time\s+(.+)$',text,re.M)
            dirs=re.findall(r'\b(NB|SB|EB|WB)\s*,',headers[1] if headers else '')
            if len(dirs)!=16 or any(dirs[i:i+2]!=dirs[:2] for i in range(0,16,2)) or len(set(dirs[:2]))!=2:
                raise ValueError(f'Page {page}: expected two directions for each of eight column groups')
            hours=[]; columns=[[] for _ in range(16)]
            for line in text.splitlines():
                m=re.match(r'^\s*(\d{1,2}):00\s*(AM|PM)?\s+(.+)$',line)
                if not m: continue
                hour=len(hours)
                if hour>=24: raise ValueError('More than 24 hourly rows')
                expected=(hour%12 or 12)
                if int(m[1])!=expected or (m[2] and m[2]!=('AM' if hour<12 else 'PM')):
                    raise ValueError(f'Page {page}: unexpected time sequence')
                values=m[3].split()
                if len(values)!=16: raise ValueError(f'Page {page}: expected 16 count cells')
                parsed=[number(v) for v in values]
                for col,value in enumerate(parsed):
                    columns[col].append(value)
                    group=col//2
                    if group==5: continue  # Weekday Average is not an observation.
                    offset=group if group<5 else group-1
                    add(monday+timedelta(days=offset),hour,dirs[col],value,page)
                hours.append(hour)
            if len(hours)!=24: raise ValueError(f'Page {page}: found {len(hours)} hourly rows, expected 24')
            total=re.search(r'^Total\s+(.+)$',text,re.M)
            if not total or len(total[1].split())!=16: raise ValueError('Missing printed daily totals')
            totals=[number(v) for v in total[1].split()]
            for col in range(16):
                if col//2==5: continue
                if any(v is not None for v in columns[col]) and sum(v or 0 for v in columns[col])!=totals[col]:
                    raise ValueError(f'Page {page}: hourly sum differs from printed total, column {col+1}')
    elif 'Full Length' in first:
        current_day=None; full_totals=defaultdict(int); printed=False
        for page,text in enumerate(texts,1):
            if re.search(r'\b(?:Midday Peak|AM Peak|PM Peak)\b',text): break
            if 'Full Length' in text and page>1: break  # Full-length chart, not another count table.
            direction_line=re.search(r'^Direction\s+(.+)$',text,re.M)
            names=re.findall(r'Northbound|Southbound|Eastbound|Westbound',direction_line[1] if direction_line else '',re.I)
            header=re.search(r'^Time\s+(.+)$',text,re.M)
            if not header: continue
            groups=re.split(r'\bApp',header[1])
            if len(names) not in (1,2) or len(groups)!=len(names)+1 or 'Int' not in groups[-1]:
                raise ValueError(f'Page {page}: unrecognized lane-total header')
            lanes=[len(re.findall(r'Lane\s+\d+|\bT\b',g)) for g in groups[:-1]]
            if not all(lanes): raise ValueError('Missing lane columns')
            app_indices=[];cursor=0
            for count in lanes:app_indices.append(cursor+count);cursor+=count+1
            expected=cursor+1
            for line in text.splitlines():
                m=re.match(r'^(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{1,2}):(\d{2})\s*(AM|PM)\s+(.+)$',line.strip())
                if m:
                    if m[1]: current_day=datetime.strptime(m[1],'%Y-%m-%d').date()
                    if current_day is None or m[3]!='00': raise ValueError('Missing date or non-hourly row in full-length table')
                    hour=int(m[2])%12+(12 if m[4]=='PM' else 0)
                    values=[number(v) for v in m[5].split()]
                    if len(values)!=expected: raise ValueError(f'Page {page}: unexpected count columns')
                    if any(v is None for v in values): raise ValueError('Missing lane counts need layout review')
                    cursor=0;valid=True
                    for count,index in zip(lanes,app_indices):
                        valid &= sum(values[cursor:index])==values[index];cursor=index+1
                    if not valid or sum(values[i] for i in app_indices)!=values[-1]:
                        raise ValueError(f'Page {page}: lane/direction totals do not reconcile')
                    for name,index in zip(names,app_indices):
                        direction=DIRECTIONS[name.lower()]
                        add(current_day,hour,direction,values[index],page)
                        full_totals[direction]+=values[index]
                elif re.match(r'^Total\s+',line):
                    values=[number(v) for v in re.sub(r'^Total\s+','',line).split()]
                    if len(values)!=expected: raise ValueError('Unexpected full-period total columns')
                    for name,index in zip(names,app_indices):
                        if full_totals[DIRECTIONS[name.lower()]]!=values[index]: raise ValueError('Full-period hourly sum differs from printed total')
                    printed=True
        if not printed: raise ValueError('Full-period printed total not found')
    else: raise ValueError('Unsupported report layout')
    # Remove calendar placeholder days with no observations in weekly reports.
    observed={(r['CountDate'],r['Direction']) for r in records if r['Volume'] is not None}
    records=[r for r in records if (r['CountDate'],r['Direction']) in observed]
    if not records: raise ValueError('No hourly volume observations')
    direction_source=path.name
    if any(r['Direction']=='UNKNOWN' for r in records):
        companion_stem=re.sub(r'_60\s*Min(?:ute)?\s*Volume(?:\s*\(\d+\))?$', '',path.stem,flags=re.I)
        companions=[p for p in path.parent.glob('*.pdf') if re.fullmatch(re.escape(companion_stem)+r'_60\s*Min\s*Class(?:\s*\(\d+\))?\.pdf',p.name,re.I)]
        header_directions=set()
        for companion in companions:
            with pdfplumber.open(companion) as other:
                for page in other.pages:
                    header_directions.update(re.findall(r'\bDirection:\s*(NB|SB|EB|WB)\s*,',page.dedupe_chars().extract_text() or ''))
        if len(header_directions)==1:
            for r in records:r['Direction']=next(iter(header_directions))
            direction_source='; '.join(p.name for p in companions)+' (direction header only)'
    latitude=re.search(r'Latitude:\s*(-?\d+\.\d+)',first)
    longitude=re.search(r'Longitude:\s*(-?\d+\.\d+)',first)
    location=re.search(r'Location:\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)',first)
    for r in records:
        r['DirectionSource']=direction_source
        r['Latitude']=latitude[1] if latitude else location[1] if location else ''
        r['Longitude']=longitude[1] if longitude else location[2] if location else ''
    return records

def write_csv(path,fields,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source',type=Path,default=SOURCE)
    p.add_argument('--output',type=Path,default=OUTPUT)
    p.add_argument('--locations',type=Path,help='Optional ATR_Locations.csv for coordinates and PDF coverage')
    args=p.parse_args()
    if not args.source.exists(): raise FileNotFoundError(args.source)
    paths=[args.source] if args.source.is_file() else sorted(args.source.rglob('*'))
    paths=[x for x in paths if x.is_file() and TARGET.search(x.name) and not any(v.casefold()=='void' for v in x.parts)]
    if not paths: raise ValueError('No hourly volume/60 Minute PDFs found')
    coords={}; expected=set()
    if args.locations:
        with args.locations.open(encoding='utf-8-sig',newline='') as f:
            for r in csv.DictReader(f):
                key=(r['Folder'].replace('\\','/').strip('/'),r['PDF_File'])
                coords[key]=(r['Latitude'],r['Longitude'])
                if TARGET.search(r['PDF_File']): expected.add(key)
    rows=[];log=[];seen={};conflicts=[];coverage=[];found=set()
    for path in paths:
        label=path.name if args.source.is_file() else path.relative_to(args.source).as_posix()
        folder='' if args.source.is_file() else path.parent.relative_to(args.source).as_posix().strip('.')
        key=(folder,path.name);found.add(key)
        try:
            data=extract(path)
            for r in data:
                lat,lon=coords.get(key,(r['Latitude'],r['Longitude']))
                r.update(SourceFile=label,Latitude=lat,Longitude=lon)
            for r in data:
                k=tuple(r[f] for f in ('StationID','CountDate','Direction','HourStart'))
                if k in seen:
                    old=seen[k]
                    if old['Volume']!=r['Volume']:
                        conflicts.append(dict(StationID=k[0],CountDate=k[1],Direction=k[2],HourStart=k[3],FirstVolume=old['Volume'],OtherVolume=r['Volume'],FirstFile=old['SourceFile'],OtherFile=label))
                else:seen[k]=r
            note='Direction not specified in PDF; exported as UNKNOWN.' if any(r['Direction']=='UNKNOWN' for r in data) else ''
            coverage.append(dict(SourceFile=label,Status='Read',HourlyRows=len(data),Detail=note))
            log.append(f'OK {label}: {len(data)} hourly directional rows')
        except Exception as exc:
            coverage.append(dict(SourceFile=label,Status='FAILED',HourlyRows=0,Detail=str(exc)))
            log.append(f'FAILED {label}: {exc}')
        print(log[-1],flush=True)
    for folder,name in sorted(expected-found):
        coverage.append(dict(SourceFile=folder+'/'+name,Status='NOT FOUND',HourlyRows=0,Detail='Listed in locations file but not found under source'))
    conflict_keys={tuple(r[f] for f in ('StationID','CountDate','Direction','HourStart')) for r in conflicts}
    rows=[r for k,r in seen.items() if k not in conflict_keys]
    rows.sort(key=lambda r:(int(r['StationID'].split()[1]),datetime.strptime(r['CountDate'],'%m/%d/%Y'),r['Direction'],r['HourStart']))
    days=defaultdict(dict)
    for r in rows:days[(r['StationID'],r['CountDate'],r['Direction'])][int(r['HourStart'][:2])]=r
    daily=[]
    for (station,date,direction),hours in days.items():
        valid=[r['Volume'] for r in hours.values() if r['Volume'] is not None]
        row=dict(StationID=station,CountDate=date,Direction=direction)
        row.update({f'H{h+1:02d}':hours.get(h,{}).get('Volume') for h in range(24)})
        row.update(Total=sum(valid) if valid else None,HoursPresent=len(valid),CompleteDay=int(len(valid)==24))
        daily.append(row)
    args.output.mkdir(parents=True,exist_ok=True)
    out=Path(tempfile.mkdtemp(prefix=datetime.now().strftime('pdf_volume_%Y%m%d_%H%M%S_'),dir=args.output))
    write_csv(out/'hourly_volume.csv',['StationID','CountDate','HourStart','Direction','Volume','Latitude','Longitude','Description','SourceFile','SourcePage','DirectionSource'],rows)
    write_csv(out/'daily_volume.csv',['StationID','CountDate','Direction']+[f'H{h:02d}' for h in range(1,25)]+['Total','HoursPresent','CompleteDay'],daily)
    write_csv(out/'file_coverage.csv',['SourceFile','Status','HourlyRows','Detail'],coverage)
    if conflicts:write_csv(out/'conflicts.csv',['StationID','CountDate','Direction','HourStart','FirstVolume','OtherVolume','FirstFile','OtherFile'],conflicts)
    log.append(f'Files: {len(paths)}; hourly rows: {len(rows)}; directional days: {len(daily)}; conflicts: {len(conflict_keys)}')
    log.append('Conflicting hours excluded. Missing hours stay blank. H01 = 00:00-01:00. Total sums available hours only.')
    log.append('All Classes totals are retained as printed, including bicycles where the provider includes them.')
    (out/'processing_log.txt').write_text('\n'.join(log)+'\n',encoding='utf-8')
    print(log[-3]);print(f'Output: {out.resolve()}')
    return 1 if conflicts or any(r['Status']!='Read' for r in coverage) else 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,ImportError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);raise SystemExit(1)
