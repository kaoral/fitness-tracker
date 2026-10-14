"""Small Plotly figure dictionaries; all calculations stay in Python.

The browser loads Plotly.js locally, so charts need no Python plotting package.
Date axes use Berlin wall time; the full UTC offset is retained in source/CSV data.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta


def local_time(value):
    return datetime.fromisoformat(value).replace(tzinfo=None).isoformat()


def chart(key, title, description, traces, y_title='', **layout):
    usable = any(any(v is not None for v in t.get('y', t.get('values', []))) for t in traces)
    return {
        'id': key, 'title': title, 'description': description,
        'empty_message': 'No recorded measurements in this selection.',
        'figure': {'data': traces if usable else [], 'layout': {
            'margin': {'l': 56, 'r': 24, 't': 16, 'b': 48},
            'height': 290, 'hovermode': 'closest',
            'yaxis': {'title': {'text': y_title}, 'automargin': True},
            'xaxis': {'automargin': True},
            'legend': {'orientation': 'h', 'y': 1.12},
            'showlegend': len(traces) > 1, **layout,
        }},
    }


def line(name, xs, ys, markers=False):
    return {'type': 'scatter', 'mode': 'lines+markers' if markers else 'lines',
            'name': name, 'x': xs, 'y': ys, 'connectgaps': False,
            'line': {'width': 2}, 'marker': {'size': 5}}


def bar(name, xs, ys):
    return {'type': 'bar', 'name': name, 'x': xs, 'y': ys}


def workout_charts(workouts):
    monthly = defaultdict(float)
    for w in workouts:
        if w['date'] and w['distance_km'] is not None:
            monthly[w['date'][:7]] += w['distance_km']
    months = sorted(monthly)
    types = Counter(w['type_label'] for w in workouts)
    ordered = sorted((w for w in workouts if w['date']), key=lambda w: (w['date'], w['id']))
    pace_traces = []
    for label in sorted({w['type_label'] for w in ordered}):
        rows = [w for w in ordered if w['type_label'] == label and w['avg_pace_s'] is not None]
        if rows:
            pace_traces.append({'type': 'scatter', 'mode': 'markers', 'name': label,
                'x': [w['date'] for w in rows], 'y': [w['avg_pace_s'] / 60 for w in rows],
                'marker': {'size': 8}, 'text': [f"Workout {w['id']}" for w in rows]})
    return [
        chart('workout-volume', 'Recorded training volume', 'Distance by month with recorded workouts. Gaps do not establish inactivity.',
              [bar('Distance', months, [round(monthly[m], 2) for m in months])], 'km'),
        chart('workout-types', 'Activity mix', 'Sessions by verified workout type, within your selection.',
              [bar('Sessions', list(types), list(types.values()))], 'sessions', yaxis={'title': {'text': 'sessions'}, 'dtick': 1}),
        chart('workout-pace', 'Pace across sessions', 'Recorded average pace, separated by activity. Lower values mean faster pace.',
              pace_traces, 'min/km'),
    ]


def recent_days(daily, predicate, days=31):
    present = [d['date'] for d in daily if predicate(d)]
    if not present:
        return []
    last = datetime.fromisoformat(max(present)).date()
    first = (last - timedelta(days=days-1)).isoformat()
    return [d for d in daily if first <= d['date'] <= last.isoformat()]


def overview_charts(data):
    days = recent_days(data['daily'], lambda d: d['recorded_minutes'] is not None)
    charts = [chart('overview-steps', 'Recorded daily steps', 'Latest activity window · unrecorded days are gaps, not zero steps.',
        [bar('Steps', [d['date'] for d in days], [d['steps'] for d in days])], 'steps')]
    charts += workout_charts(data['workouts'])[:1]
    sleep_days = recent_days(data['daily'], lambda d: d['sleep_hours'] is not None)
    charts.append(chart('overview-sleep', 'Recorded sleep duration', 'Sleep intervals grouped by wake date. Missing recordings remain gaps.',
        [line('Recorded sleep', [d['date'] for d in sleep_days], [d['sleep_hours'] for d in sleep_days], True)], 'hours'))
    readings = data['stress']
    charts.append(chart('overview-stress', 'Stress readings', 'Device-reported samples; this is not continuous stress monitoring.',
        [{'type': 'scatter', 'mode': 'markers', 'name': 'Stress', 'x': [local_time(r['timestamp_iso']) for r in readings],
          'y': [r['value'] for r in readings], 'marker': {'size': 6}}], 'reported score'))
    return charts


def detail_charts(workout, details):
    samples = details['samples']
    xs = [local_time(r['timestamp_iso']) for r in samples]
    result = [chart('detail-heart-rate', 'Workout heart rate', 'Recorded samples · Berlin local time.',
        [line('Heart rate', xs, [r['heart_rate'] for r in samples])], 'bpm'),
        chart('detail-pace', 'Workout pace', 'Derived from recorded speed. Stationary samples have no pace.',
        [line('Pace', xs, [r['pace_min_km'] for r in samples])], 'min/km'),
        chart('detail-elevation', 'Elevation profile', 'Recorded altitude · decimetres converted to metres.',
        [line('Altitude', xs, [r['altitude_m'] for r in samples])], 'm')]
    splits = details['splits']
    result.append(chart('detail-splits', 'Recorded splits', 'Pace for splits supplied by the export; a final split may be shorter.',
        [bar('Pace', [s['label'] for s in splits], [s['pace_s']/60 if s['pace_s'] is not None else None for s in splits])], 'min/km'))
    zones = workout['zones']
    if zones:
        result.append(chart('detail-zones', 'Reported heart-rate zones', 'Zone durations supplied by Gadgetbridge, using its configured zone definitions.',
            [bar('Duration', [z['label'] for z in zones], [z['seconds']/60 for z in zones])], 'minutes'))
    return result


def daily_charts(day, details):
    activity = details['activity']
    hourly = defaultdict(list)
    for r in activity:
        hourly[datetime.fromisoformat(r['timestamp_iso']).hour].append(r)
    hours = [f'{h:02d}:00' for h in range(24)]
    steps = [sum(r['steps'] for r in hourly[h] if r['steps'] is not None) if hourly[h] and any(r['steps'] is not None for r in hourly[h]) else None for h in range(24)]
    # Insert explicit gaps when the sensor has no readings for over five minutes.
    xs, hrs, resting = [], [], []
    previous = None
    for r in activity:
        timestamp = datetime.fromisoformat(r['timestamp_iso'])
        if previous and (timestamp - previous).total_seconds() > 300:
            xs.append(local_time(r['timestamp_iso'])); hrs.append(None); resting.append(None)
        xs.append(local_time(r['timestamp_iso'])); hrs.append(r['heart_rate']); resting.append(r['resting_hr'])
        previous = timestamp
    readings = details['stress']
    return [chart('daily-steps', 'Steps by hour', 'Sum of recorded step intervals. Empty hours have no recorded data.', [bar('Steps', hours, steps)], 'steps'),
        chart('daily-heart-rate', 'Heart-rate readings', 'Measured samples and recorded resting-HR values · no daily resting-HR estimate is inferred.',
            [line('Heart rate', xs, hrs), line('Recorded resting HR', xs, resting)], 'bpm'),
        chart('daily-stress', 'Stress throughout the day', 'Each point is a device-reported reading.',
            [{'type':'scatter','mode':'markers','name':'Stress','x':[local_time(r['timestamp_iso']) for r in readings], 'y':[r['value'] for r in readings], 'marker':{'size':7}}], 'reported score')]


def sleep_charts(sleeps):
    totals = defaultdict(float)
    for r in sleeps:
        totals[r['date']] += r['duration_hours']
    dates, values = [], []
    if totals:
        current = datetime.fromisoformat(min(totals)).date()
        end = datetime.fromisoformat(max(totals)).date()
        while current <= end:
            key = current.isoformat(); dates.append(key); values.append(totals.get(key)); current += timedelta(days=1)
    return [chart('sleep-duration', 'Recorded sleep by wake date', 'Actual recorded intervals only. Short recording gaps are excluded from duration.',
        [line('Recorded sleep', dates, values, True)], 'hours')]


def stress_charts(readings):
    grouped = defaultdict(list)
    for r in readings:
        grouped[r['date']].append(r['value'])
    days = sorted(grouped)
    return [chart('stress-readings', 'Stress readings over time', 'Individual device-reported samples · Berlin local time.',
        [{'type':'scatter','mode':'markers','name':'Stress','x':[local_time(r['timestamp_iso']) for r in readings], 'y':[r['value'] for r in readings], 'marker':{'size':6}}], 'reported score'),
        chart('stress-samples', 'Recording frequency', 'Sample counts help put daily averages into context.',
        [bar('Readings', days, [len(grouped[d]) for d in days])], 'readings')]
