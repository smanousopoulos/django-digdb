=====
DigDB
=====

DigDB is a Django app for archaeological excavations publishing. Given the table schemas (see below) it creates a basic sceleton web application with viewing and editing capabilities through a web UI and REST APIs. 

Detailed documentation will be available soon.

Quick start
-----------

1. Add "digdb" to your INSTALLED_APPS setting like this::

    INSTALLED_APPS = [
        ...
        'multiselectfield',
        'haystack',
        'rest_framework',
        'import_export',
        'digdb',
    ]

2. Run `python manage.py import_schema path/to/schema(ta)/dir/` to initialize the app with the given schema(ta)

3. Run `python manage.py migrate` to create the DigDB models.

4. Include the digdb URLconf in your project urls.py like this::

    url(r'^/', include('digdb.urls')),

5. Start the development server and visit http://127.0.0.1:8000/admin/
   to create a new entry of any of the schemata you inserted.

5. Visit http://127.0.0.1:8000/ to view the default search page.


Schema file format
------------------

Currently the only input format supported is the XLSForm Excel file format. For more details on the XLSForm file format and sample Excel file see https://opendatakit.org/use/xlsform/. 

JSON format is planned to be supported.


