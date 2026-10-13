# School Monitor

Django school management system. Local development only.

## Run

    cd /e/my-works/web_development/Django/school_monitor
    source venv/Scripts/activate
    cd school_monitor
    python manage.py runserver

Open http://127.0.0.1:8000/

## Demo logins

| Role    | Username    | Password    |
|---------|-------------|-------------|
| Admin   | admin       | admin123    |
| Teacher | teacher1-6  | teacher123  |
| Parent  | parent1-20  | parent123   |

## Reset demo data

    python manage.py seed_data --reset

## Notes

- `DEBUG = True`, SQLite, hardcoded `SECRET_KEY` — not production-safe.
- `db.sqlite3` and `media/` are gitignored.