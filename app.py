"""Local Flask dashboard: routes prepare data; Jinja handles presentation."""
from datetime import date, datetime
import csv
import io
import math
import sqlite3
from zoneinfo import ZoneInfo

from flask import Flask, Response, abort, g, render_template, request

import analytics
import charts as figures
import database

DISPLAY_TIMEZONE = ZoneInfo('Europe/Berlin')


def number(value, decimals=0):
    if value is None or value == -1:
        return '—'
    if isinstance(value, str):
        return value
    if not math.isfinite(value):
        return '—'
    return f'{value:,.{decimals}f}'


def format_duration(seconds):
    if seconds is None or seconds == -1:
        return '—'
    hours, remainder = divmod(round(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours}h {minutes}m {seconds}s' if hours else f'{minutes}m {seconds}s'


def pace(seconds):
    if seconds is None or seconds <= 0:
        return '—'
    minutes, remainder = divmod(round(seconds), 60)
    return f'{minutes}:{remainder:02d}'


def datetime_label(value):
    if not value:
        return '—'
    return datetime.fromisoformat(value).astimezone(DISPLAY_TIMEZONE).strftime('%d %b %Y, %H:%M')


def snapshot():
    if 'fitness_data' not in g:
        g.fitness_data = analytics.load_data()
    return g.fitness_data


def validated_date(name):
    value = request.args.get(name, '').strip()
    if value:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            abort(400, description=f'Please enter a valid {name} date in YYYY-MM-DD format.')
    return value


def filters(include_type=False):
    result = {'start': validated_date('start'), 'end': validated_date('end')}
    if result['start'] and result['end'] and result['start'] > result['end']:
        abort(400, description='The start date must be on or before the end date.')
    if include_type:
        result['type'] = request.args.get('type', '').strip()
        if result['type']:
            try:
                int(result['type'])
            except ValueError:
                abort(400, description='Choose a valid workout type.')
        result['sort'] = request.args.get('sort', 'newest')
        if result['sort'] not in {'newest', 'oldest', 'distance', 'duration'}:
            abort(400, description='Choose a valid workout sort order.')
    return result


def select_dates(rows, chosen):
    return [r for r in rows if (not chosen['start'] and not chosen['end']) or (r['date'] and (not chosen['start'] or r['date'] >= chosen['start']) and (not chosen['end'] or r['date'] <= chosen['end']))]


def selected_workouts(rows, chosen):
    rows = select_dates(rows, chosen)
    if chosen['type']:
        rows = [r for r in rows if r['type_code'] == int(chosen['type'])]
    order = chosen['sort']
    if order in {'distance', 'duration'}:
        field = 'distance_km' if order == 'distance' else 'duration_s'
        return sorted(rows, key=lambda r: (r[field] is not None, r[field] or 0, datetime.fromisoformat(r['start_iso']).timestamp() if r['start_iso'] else float('-inf'), r['id']), reverse=True)
    return sorted(rows, key=lambda r: (datetime.fromisoformat(r['start_iso']).timestamp() if r['start_iso'] else float('-inf'), r['id']), reverse=order == 'newest')


def stat(label, value, unit='', detail=''):
    return {'label': label, 'value': value, 'unit': unit, 'detail': detail}


def sum_available(rows, field):
    values = [r[field] for r in rows if r[field] is not None]
    return sum(values) if values else None


def workout_stats(rows):
    return [stat('Recorded workouts', number(len(rows)), detail='Within this selection'),
        stat('Total distance', number(sum_available(rows, 'distance_km'), 1), 'km', 'Recorded workout distance'),
        stat('Active time', format_duration(sum_available(rows, 'duration_s')), detail='Recorded active duration'),
        stat('Reported calories', number(sum_available(rows, 'calories')), 'kcal', 'Device-reported estimates')]


def create_app(test_config=None):
    app = Flask(__name__)
    if test_config:
        app.config.update(test_config)
    database.init_app(app)
    app.jinja_env.globals.update(number=number, duration=format_duration, pace=pace, datetime_label=datetime_label)
    app.jinja_env.filters.update(number=number, duration=format_duration, pace=pace, datetime_label=datetime_label)

    def page(template, title, active, **context):
        data = snapshot()
        return render_template(template, page_title=title, active_page=active, database_error=False,
            warnings=data['warnings'], **context)

    @app.after_request
    def private_responses(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(sqlite3.Error)
    def database_unavailable(error):
        app.logger.exception('Unable to read the local Gadgetbridge export')
        return render_template('error.html', page_title='Database unavailable', active_page='', warnings=[], database_error=True,
            message='The fitness database is unavailable. Check that your local export is at instance/Gadgetbridge.db.', status=503), 503

    @app.errorhandler(400)
    @app.errorhandler(404)
    def request_error(error):
        return render_template('error.html', page_title='Check your selection' if error.code == 400 else 'Page not found',
            active_page='', warnings=[], database_error=False, message=error.description, status=error.code), error.code

    @app.get('/')
    def home():
        data = snapshot()
        activity = next((r for r in data['coverage'] if r['key'] == 'activity'), None)
        stats = workout_stats(data['workouts'])[:3] + [stat('Activity days', number(activity['observed_days']) if activity else '—', detail='Days with recorded activity')]
        return page('home.html', 'Overview', 'home', stats=stats, charts=figures.overview_charts(data),
            latest_workouts=data['workouts'][:5], coverage=data['coverage'])

    @app.get('/data_overview')
    def data_overview():
        data = snapshot(); chosen = filters(True)
        workouts = selected_workouts(data['workouts'], chosen)
        types = sorted({(r['type_code'], r['type_label']) for r in data['workouts'] if r['type_code'] is not None})
        return page('data_overview.html', 'Workouts', 'data_overview', workouts=workouts,
            types=[{'code': c, 'label': label} for c, label in types], filters=chosen,
            stats=workout_stats(workouts), charts=figures.workout_charts(workouts))

    @app.get('/workouts/<int:workout_id>')
    def workout_detail(workout_id):
        data = snapshot()
        workout = next((w for w in data['workouts'] if w['id'] == workout_id), None)
        if workout is None:
            abort(404, description='That workout is not present in this export.')
        details = analytics.get_workout_details(workout_id)
        return page('workout_detail.html', f'Workout {workout_id}', 'data_overview', workout=workout,
            details=details, charts=figures.detail_charts(workout, details))

    @app.get('/daily')
    def daily():
        data = snapshot()
        observed = [d['date'] for d in data['daily'] if d['recorded_minutes'] is not None or d['hr_count'] or d['sleep_hours'] is not None or d['stress_count'] or d['workout_count']]
        chosen = validated_date('date') or (max(observed) if observed else datetime.now(DISPLAY_TIMEZONE).date().isoformat())
        day = next((d for d in data['daily'] if d['date'] == chosen), None)
        if day and not (day['recorded_minutes'] is not None or day['hr_count'] or day['sleep_hours'] is not None or day['stress_count'] or day['workout_count']):
            day = None
        details = analytics.get_day_details(chosen)
        previous = [d for d in observed if d < chosen]; following = [d for d in observed if d > chosen]
        return page('daily.html', 'Daily activity', 'daily', selected_date=chosen, day=day, details=details,
            previous_date=max(previous) if previous else None, next_date=min(following) if following else None,
            charts=figures.daily_charts(day, details))

    @app.get('/sleep')
    def sleep():
        data = snapshot(); chosen = filters(); rows = select_dates(data['sleep'], chosen)
        hours = [r['duration_hours'] for r in rows]
        stats = [stat('Recorded sessions', number(len(rows)), detail='TruSleep source 10'),
            stat('Mean session', number(sum(hours)/len(hours) if hours else None, 1), 'hours', 'Based on recorded intervals'),
            stat('Recorded sleep', number(sum(hours) if hours else None, 1), 'hours', 'Within this selection')]
        return page('sleep.html', 'Sleep', 'sleep', sleeps=list(reversed(rows)), filters=chosen, stats=stats, charts=figures.sleep_charts(rows))

    @app.get('/stress')
    def stress():
        data = snapshot(); chosen = filters(); rows = select_dates(data['stress'], chosen)
        values = [r['value'] for r in rows]
        stats = [stat('Readings', number(len(rows)), detail='Device-reported samples'),
            stat('Sampled mean', number(sum(values)/len(values) if values else None, 1), detail='Average of available readings'),
            stat('Observed days', number(len({r['date'] for r in rows})), detail='Days with at least one reading')]
        return page('stress.html', 'Stress', 'stress', readings=list(reversed(rows)), filters=chosen, stats=stats, charts=figures.stress_charts(rows))

    @app.get('/sources')
    def sources():
        return page('sources.html', 'Data sources', 'sources', coverage=snapshot()['coverage'])

    @app.get('/settings')
    def settings():
        # Appearance stays available even when a local export is not installed.
        return render_template('settings.html', page_title='Appearance', active_page='settings', database_error=False, warnings=[])

    @app.get('/exports/<kind>.csv')
    def export_data(kind):
        columns = {
            'workouts': ['id','start_iso','date','type_code','type_label','distance_km','duration_s','steps','calories','avg_hr','max_hr','avg_pace_s','elevation_gain_m'],
            'daily': ['date','steps','recorded_minutes','hr_avg','hr_min','hr_max','hr_count','sleep_hours','stress_avg','stress_min','stress_max','stress_count','workout_count','workout_distance_km','workout_duration_s'],
            'sleep': ['date','start_iso','end_iso','duration_hours'],
            'stress': ['date','timestamp_iso','value'],
        }
        if kind not in columns:
            abort(404, description='That export type is not available.')
        data = snapshot()
        chosen = filters(kind == 'workouts')
        rows = selected_workouts(data[kind], chosen) if kind == 'workouts' else select_dates(data[kind], chosen)
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=columns[kind]+['timezone'], extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, 'timezone': 'Europe/Berlin'})
        return Response(output.getvalue(), mimetype='text/csv', headers={
            'Content-Disposition': f'attachment; filename="fitness-{kind}.csv"',
        })

    return app


app = create_app()
