from os import listdir, makedirs
from os.path import isfile, join, splitext, exists, dirname
from distutils.sysconfig import get_python_lib
import errno
import re
import json
from collections import OrderedDict
from pyxform import xls2json
from jinja2 import Environment, PackageLoader

from django.core.management.base import BaseCommand, CommandError

from ...apps import DigDBConfig
        
PREFERED_LANG_DEFAULT = 'english'
APP_NAME = DigDBConfig.name


REGEX_VALIDATOR = 'from django.core.validators import RegexValidator'
MINLENGTH_VALIDATOR = 'from django.core.validators import MinLengthValidator'

class Command(BaseCommand):
    help = 'Auto-generates django admin & models & views from XFORM xls/xlsx'

    lang = PREFERED_LANG_DEFAULT
    models = OrderedDict()
    sec_models = OrderedDict()
    indexed = {}
    faceted = {}
    order = 0
    def add_arguments(self, parser):
        parser.add_argument('input', type=str)
        parser.add_argument('--output', type=str)
        parser.add_argument('--debug', action='store_true')
        parser.add_argument('--lang', type=str)
        #parser.add_argument('--viewonly', action='store_true')
    
    def handle(self, *args, **options): 
        self.static = {
            'choices': {}
        }

        output_dir = options['output'] if options['output'] else join(get_python_lib(), APP_NAME)
        if options['lang']:
            self.lang = options['lang']

        # Parse files
        files = [join(options['input'], f) for f in listdir(options['input']) if isfile(join(options['input'], f)) and (splitext(f)[1] == '.xls' or splitext(f)[1] == '.xlsx')]

        self.stdout.write(self.style.SUCCESS('Found %d files\n' % len(files)))

        for fin in files:
            self.order += 1
            json_data = self.read_json_from_file(fin)
            name, model = self._parse_entrypoint(json_data)
            self.models[name] = model
         
        env = Environment(loader=PackageLoader(APP_NAME, 'templates'), trim_blocks=True)

        # Load templates
        models_template = env.get_template('models.py.j2')
        indexes_template = env.get_template('search_indexes.py.j2')
        admin_template = env.get_template('admin.py.j2')
        serializers_template = env.get_template('serializers.py.j2')
        urls_template = env.get_template('urls.py.j2')
        views_template = env.get_template('views.py.j2')
        search_metatemplate = env.get_template('search.html.j2')
        index_text_template = env.get_template('index_text.txt.j2')
        index_rendered_template = env.get_template('index_rendered.txt.j2')
        fieldlist_metatemplate = env.get_template('field_list.html.j2')
        fielddetails_metatemplate = env.get_template('field_details.html.j2')

        self.stdout.write(self.style.WARNING('\nCreating files from templates...\n'))
        
        # Create files
        self.render_template(urls_template, 'urls.py', output_dir)
        self.render_template(views_template, 'views.py', output_dir)
        self.render_template(fieldlist_metatemplate, 'field_list.html', join(output_dir, 'jinja2'))
        self.render_template(fielddetails_metatemplate, 'field_details.html', join(output_dir, 'jinja2'))
        self.render_template(search_metatemplate, 'search.html', join(output_dir, 'jinja2', 'search'))
        
        self.render_template(models_template, 'models.py', output_dir, static=self.static)
        self.render_template(indexes_template, 'search_indexes.py', output_dir)
        self.render_template(admin_template, 'admin.py', output_dir)
        self.render_template(serializers_template, 'serializers.py', output_dir)

        all_models = self.models.copy()
        all_models.update(self.sec_models)
        for name, model in all_models.iteritems():
            self.render_template(index_text_template, '{0}_text.txt'.format(''.join(name.split("_"))), join(output_dir, 'jinja2', 'search', 'indexes', APP_NAME), model=model)
            self.render_template(index_rendered_template, '{0}_rendered.txt'.format(''.join(name.split("_"))), join(output_dir, 'jinja2', 'search', 'indexes', APP_NAME), model=model)
 
        if options['debug']:
            with open(join(output_dir, 'out.json'), 'w') as json_out:
                json.dump(self.models, json_out, indent=4)

            with open(join(output_dir, 'out_sec.json'), 'w') as json_out:
                json.dump(self.sec_models, json_out, indent=4)

    # Parse input JSON to model JSON functions
    def _parse_entrypoint (self, form):
        name, class_name, label = self._get_form_name_class_label(form)
        
        # heuristics to set default field for class representation
        #TODO: should be set explicitly
        for f in form.get('children'):
            if type(f.get('bind')) is dict:
                if (f.get('bind').get('required') and (f.get('type') == 'string' or f.get('type') == 'text' or f.get('type') == 'select one')):
                    break
        parent_class = ''
        parent_label = ''

        model = {
                'meta': {
                    'name': name,
                    'label': u'{0}'.format(label),
                    'class': '{0}'.format(class_name),
                    'order': self.order
                    },
                'secondary': {},
                'var': OrderedDict(),
                'fn': {},
                'fieldsets': OrderedDict()
                }
        
        for field in form.get('children'):
            self._parse_generic(model, field) 
    
        # Find thumbnail
        model['meta']['thumb'] = {
                'found': False,
        }
        for n, f in model['var'].iteritems():
            if f.get('type') == 'ImageWithThumbsField':
                model['meta']['thumb'] = {
                        'type': 'self',
                        'found': True,
                        'field': n,
                }
                break

        if not model['meta']['thumb']['found']:
            for sec_name, sec_val in model['secondary'].iteritems():
                for n, f in self.sec_models[sec_name]['var'].iteritems():
                    if f.get('type') == 'ImageWithThumbsField':
                        model['meta']['thumb'] = {
                                'type': 'rel',
                                'found': True,
                                'sec_model': sec_name,
                                'field': n,
                        }
                        break
        return name, model

    def _parse_generic(self, model, field):
        if field.get('type') == 'group':
            self._parse_group(model, field) 
        elif field.get('type') == 'repeat':
            self._parse_repeat(model, field)
        elif field.get('type').startswith('select'):
            self._parse_field(model, field)
            self._parse_select(model, field)
        else:
            self._parse_field(model, field)
    
    def _parse_field(self, model, field):
        name, parsed = self._get_field(field)
        if parsed:
            if parsed.get('id_field'):
                model['meta']['id'] = name
                del parsed['id_field']
            if parsed.get('description_field'):
                model['meta']['description'] = name
                del parsed['description_field']
            model['var'][name] = parsed
   
    def _parse_group(self, model, group):
        name, class_name, label = self._get_form_name_class_label(group)
        if class_name == 'Meta':
            return

        fields = []
        for field in group.get('children'):
            field_name = field.get('name')
            if not field_name.startswith('generated_table_list'):
                fields.append(field_name)
            self._parse_generic(model, field)
        
        model['fieldsets'][label] = tuple(fields)

    def _parse_repeat(self, model, group):
        name, class_name, label = self._get_form_name_class_label(group)
        
        if class_name == 'Meta':
            return
        #TODO: change blank to required until template
        blank = None
        if group.get('bind'):
            if group.get('bind').get('required'):
                blank = True
        #model['fieldsets'][label] = (name,)
        #TODO reverse
        #model['var'][name] = {
        #            'type': 'ForeignKey',
        #            'model': class_name,
        #            'verbose_name': label,
        #            'blank': blank,
        #            'related_name': name
        #            }

        sec_name, sec_model = self._parse_entrypoint(group)
         
        if sec_name in self.sec_models:
            self.sec_models[sec_name]['var'][model['meta']['name']] = {
                    'type': 'ForeignKey',
                    'model': model['meta']['class'],
                    'verbose_name': model['meta']['label'],
                    'blank': blank,
                    'indexed': True,
                    'related_name': name,
                    'on_delete': 'models.CASCADE'
                    }

        else:
            sec_model['var'][model['meta']['name']] = {
                    'type': 'ForeignKey',
                    'model': model['meta']['class'],
                    'verbose_name': model['meta']['label'],
                    'blank': blank,
                    'indexed': True,
                    'related_name': name,
                    'on_delete': 'models.CASCADE'
                    }
            self.sec_models[sec_name] = sec_model

        model['secondary'][sec_name] = sec_name
        # Add reference to self

    def _parse_select(self, model, field):
        choice_name = '{0}_choices'.format(field.get('name'))
        choices = []
        for choice in field.get('choices'):
            name = choice.get('name')
            label = choice.get('label').get(self.lang) or choice.get('label')
            if not model.get('var').get(field.get('name')):
                raise Exception ('field %s not parsed' % field.get('name'))
            model.get('var').get(field.get('name'))['choices'] = choice_name 
            choices.append((name, label))

        self.static['choices'][choice_name] = tuple(choices)


    def _get_field (self, fld):
        var = {}
        var['name'] = fld.get('name')

        if fld.get('label'):
            if type(fld.get('label')) is dict:
                var['verbose_name'] = fld.get('label').get(self.lang)
            else:
                var['verbose_name'] = fld.get('label')
        if fld.get('type') == 'string' or fld.get('type') == 'select one':
            var['max_length'] = 200

        elif fld.get('type') == 'text':
            var['max_length'] = 1000

        elif fld.get('type') == 'integer':
            var['max_digits'] = 5

        elif fld.get('type') == 'decimal':
            var['decimal_places'] = 2
            var['max_digits'] = 5

        if fld.get('hint'):
            if type(fld.get('hint')) is dict:
                var['help_text'] = fld.get('hint').get(self.lang)
            else:
                var['help_text'] = fld.get('hint')

        if fld.get('default'):
            if fld.get('type') == 'date' and fld.get('default') == 'today()':
                var['default'] = 'datetime.now'
            else:
                var['default'] = fld.get('default')
        
        if fld.get('bind'):
            if fld.get('bind').get('required'):
                if fld.get('bind').get('required') == 'yes':
                    var['blank'] = 'false'
                else:
                    var['blank'] = 'true'
            
            if fld.get('bind').get('readonly') and fld.get('bind').get('readonly').startswith('true'):
                var['editable'] = 'false'
                
            if fld.get('bind').get('constraint'):
                var['validators'] = self._get_constraint(fld.get('bind').get('constraint'), fld.get('bind').get('jr:constraintMsg').get(self.lang))
        
        var['type'] = self._get_type(fld.get('type'))
        if not var['type']:
            return (None, None)
        
        if fld.get('faceted'):
            if not fld.get('name') in self.faceted:
            #if fld.get('name') == 'group_type_all':
                self.faceted[fld.get('name')] = fld.get('name')
                var['faceted'] = True

        if fld.get('unique'):
            var['unique'] = True

        if fld.get('id'):
            var['id_field'] = True

        if fld.get('description'):
            var['description_field'] = True

        # Index all char fields and textfields for now
        if var['type']=='models.CharField' or var['type'] == 'models.TextField' or var['type'] == 'models.DateField':
            #self.indexed[fld.get('name')] = fld.get('name')
            var['indexed'] = True
        return (var['name'], var)
     
    def _get_constraint (self, constraint, message):
        if constraint.startswith("string-length(.) ="):
            length = constraint.split("string-length(.) =")[1].strip()
            try:
                length = int(length)
            except ValueError:
                self.stdout.write(self.style.ERROR('Oops, non-integer found in string-length constraint: %s' % constraint))

            return u'[MinLengthValidator({0}, message="{1}"), MaxLengthValidator({0}, message="{1}")]'.format(length, message)

        elif constraint.startswith("string-length(.) <="):
            length = constraint.split("string-length(.) <=")[1].strip()
            try:
                length = int(length)
            except ValueError:
                self.stdout.write(self.style.ERROR('Oops, non-integer found in string-length constraint: %s' % constraint))
            return u'[MinLengthValidator({0}, message="{1}")]'.format(length, message)
        elif constraint.startswith("string-length(.) >="):
            length = constraint.split("string-length(.) >=")[1].strip()
            try:
                length = int(length)
            except ValueError:
                self.stdout.write(self.style.ERROR('Oops, non-integer found in string-length constraint: %s' % constraint))
            return u'[MaxLengthValidator({0}, message="{1}")]'.format(length, message)

        elif constraint.startswith("string-regex ="):
           regex = constraint.split("string-regex =")[1].strip()
           try:
               re.compile(regex)
           except re.error:
               self.stdout.write(self.style.ERROR('Oops, invalid regular expression found in string-regex constraint: %s' % constraint))
           return u'[RegexValidator("{0}", message="{1}")]'.format(regex, message)

    # Helper functions
    def _get_form_name_class_label(self, form):
        name = form.get('name') or form.get('id_string')

        label = None
        if form.get('label'):

            if type(form.get('label')) is dict:
                label = ''.join(form.get('label').get(self.lang).split('-'))
            else:
                label = form.get('label')
        elif form.get('title'):
            label = form.get('title')
        else:
            label = form.get('name')
        
        class_name = "".join(x.capitalize() for x in name.split('_'))

        return (name, class_name, label)


    def _get_type (self, ftype):
        return {
                'string': 'models.CharField',
                'text': 'models.TextField',
                'decimal': 'models.DecimalField',
                'integer': 'models.IntegerField',
                'date': 'models.DateField',
                'photo': 'ImageWithThumbsField',
                'select one': 'models.CharField',
                'select all that apply': 'MultiSelectField',
                }.get(ftype, None)

    def render_template (self, template, filename, output_dir, **extra_args):
        template_rendered = template.render(class_models=self.models, sec_models=self.sec_models, **extra_args)
        out_filename = join(output_dir, filename)
        self.dump_to_file(out_filename, template_rendered)

    def dump_to_file (self, filename, content):
        self.create_path_if_needed(filename)
        try: 
            with open(filename, 'w') as file_out:
                file_out.write(content.encode('utf-8'))
                self.stdout.write(self.style.SUCCESS('Successfully wrote to %s file' % filename))
        except IOError as ex:
            self.stdout.write(self.style.ERROR('Failure writing to %s file: %s' % (filename, ex)))

    def create_path_if_needed (self, filename):
        if not exists(dirname(filename)):
            try:
                makedirs(dirname(filename))
            except OSError as ex:
                if ex.errno != errno.EEXIST:
                    raise

    def read_json_from_file (self, filename):
        try: 
            json_data = xls2json.parse_file_to_json(filename, warnings=[])
            self.stdout.write(self.style.SUCCESS('Successfully read xls file %s' % filename))
        except IOError:
            self.stdout.write(self.style.ERROR('Failure reading xls file %s' % filename))
        return json_data
