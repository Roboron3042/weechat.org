# -*- coding: utf-8 -*-
#
# Copyright (C) 2003-2014 Sébastien Helleu <flashcode@flashtux.org>
#
# This file is part of WeeChat.org.
#
# WeeChat.org is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# WeeChat.org is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with WeeChat.org.  If not, see <http://www.gnu.org/licenses/>.
#

import gzip
from hashlib import md5
from os import chdir, listdir, path
import re
import tarfile
from xml.sax.saxutils import escape

from django import forms
from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy

from weechat.common.path import files_path_join
from weechat.download.models import Release

MAX_LENGTH_NAME = 64
MAX_LENGTH_VERSION = 32
MAX_LENGTH_MD5SUM = 256
MAX_LENGTH_DESC = 1024
MAX_LENGTH_APPROVAL = 1024
MAX_LENGTH_AUTHOR = 256
MAX_LENGTH_MAIL = 256


class Theme(models.Model):
    visible = models.BooleanField(default=False)
    name = models.CharField(max_length=MAX_LENGTH_NAME)
    version = models.CharField(max_length=MAX_LENGTH_VERSION)
    md5sum = models.CharField(max_length=MAX_LENGTH_MD5SUM, blank=True)
    desc = models.CharField(max_length=MAX_LENGTH_DESC, blank=True)
    approval = models.CharField(max_length=MAX_LENGTH_APPROVAL, blank=True)
    author = models.CharField(max_length=MAX_LENGTH_AUTHOR)
    mail = models.CharField(max_length=MAX_LENGTH_MAIL)
    added = models.DateTimeField()
    updated = models.DateTimeField()

    def __unicode__(self):
        return '%s - %s (%s, %s)' % (self.name, self.author, self.version,
                                     self.added)

    def short_name(self):
        pos = self.name.find('.')
        if pos > 0:
            return self.name[0:pos]
        return self.name

    def path(self):
        pending = ''
        if not self.visible:
            pending = '/pending'
        return 'themes%s' % pending

    def html_preview(self):
        filename = files_path_join('themes', 'html',
                                   path.basename('%s.html' % self.name))
        if path.isfile(filename):
            with open(filename, 'rb') as f:
                content = f.read()
            return content
        return ''

    def desc_i18n(self):
        if self.desc:
            return gettext_lazy(self.desc.encode('utf-8'))
        return ''

    def build_url(self):
        return '/files/%s/%s' % (self.path(), self.name)

    def file_exists(self):
        return path.isfile(files_path_join(self.path(),
                                           path.basename(self.name)))

    @staticmethod
    def get_props(themestring):
        props = {}
        for line in themestring.split('\n'):
            line = str(line.strip().decode('utf-8'))
            if line.startswith('#'):
                m = re.match('^# \\$([A-Za-z]+): (.*)', line)
                if m:
                    props[m.group(1)] = m.group(2)
        return props

    class Meta:
        ordering = ['-added']


class TestField(forms.CharField):
    def clean(self, value):
        if not value:
            raise forms.ValidationError(
                gettext_lazy('This field is required.'))
        if value.lower() != 'no':
            raise forms.ValidationError(
                gettext_lazy('This field is required.'))
        return value


class ThemeFormAdd(forms.Form):
    required_css_class = 'required'
    themefile = forms.FileField(
        label=gettext_lazy('File'),
        help_text=gettext_lazy('the theme'),
        widget=forms.FileInput(attrs={'size': '50'})
    )
    description = forms.CharField(
        required=False,
        max_length=MAX_LENGTH_DESC,
        label=gettext_lazy('Description'),
        help_text=gettext_lazy('optional'),
        widget=forms.TextInput(attrs={'size': '60'})
    )
    author = forms.CharField(
        max_length=MAX_LENGTH_AUTHOR,
        label=gettext_lazy('Your name or nick')
    )
    mail = forms.EmailField(
        max_length=MAX_LENGTH_MAIL,
        label=gettext_lazy('Your e-mail'),
        help_text=gettext_lazy('no spam, never displayed on site'),
        widget=forms.TextInput(attrs={'size': '40'})
    )
    comment = forms.CharField(
        required=False,
        max_length=1024,
        label=gettext_lazy('Comments'),
        help_text=gettext_lazy('optional, not displayed'),
        widget=forms.Textarea(attrs={'rows': '3'})
    )
    test = TestField(
        max_length=64,
        label=gettext_lazy('Are you a spammer?'),
        help_text=gettext_lazy('enter "no" if you are not a spammer'),
        widget=forms.TextInput(attrs={'size': '10'})
    )

    def clean_themefile(self):
        f = self.cleaned_data['themefile']
        if f.size > 512*1024:
            raise forms.ValidationError(gettext_lazy('Theme file too big.'))
        props = Theme.get_props(f.read())
        if 'name' not in props or 'weechat' not in props:
            raise forms.ValidationError(gettext_lazy('Invalid theme file.'))
        themes = Theme.objects.filter(name=props['name'])
        if themes:
            raise forms.ValidationError(
                gettext_lazy('This name already exists.'))
        if not props['name'].endswith('.theme'):
            raise forms.ValidationError(
                gettext_lazy('Invalid name inside theme file.'))
        shortname = props['name'][0:-6]
        if not re.search('^[A-Za-z0-9_]+$', shortname):
            raise forms.ValidationError(
                gettext_lazy('Invalid name inside theme file.'))
        release_stable = Release.objects.get(version='stable')
        release_devel = Release.objects.get(version='devel')
        if props['weechat'] not in (release_stable.description,
                                    re.sub('-.*', '',
                                           release_devel.description)):
            raise forms.ValidationError(
                gettext_lazy('Invalid WeeChat version, too old!'))
        f.seek(0)
        return f


def get_theme_choices():
    try:
        theme_list = Theme.objects.filter(visible=1).order_by('name')
        theme_choices = []
        for theme in theme_list:
            theme_choices.append((theme.id, '%s (%s)' % (theme.name,
                                                         theme.version)))
        return theme_choices
    except:
        return []


class ThemeFormUpdate(forms.Form):
    required_css_class = 'required'
    theme = forms.ChoiceField(
        choices=get_theme_choices(),
        label=gettext_lazy('Theme')
    )
    themefile = forms.FileField(
        label=gettext_lazy('File'),
        help_text=gettext_lazy('the theme'),
        widget=forms.FileInput(attrs={'size': '50'})
    )
    author = forms.CharField(
        max_length=MAX_LENGTH_AUTHOR,
        label=gettext_lazy('Your name or nick')
    )
    mail = forms.EmailField(
        max_length=MAX_LENGTH_MAIL,
        label=gettext_lazy('Your e-mail'),
        help_text=gettext_lazy('no spam, never displayed on site'),
        widget=forms.TextInput(attrs={'size': '40'})
    )
    comment = forms.CharField(
        required=False,
        max_length=1024,
        label=gettext_lazy('Comments'),
        help_text=gettext_lazy('optional, not displayed'),
        widget=forms.Textarea(attrs={'rows': '3'})
    )
    test = TestField(
        max_length=64,
        label=gettext_lazy('Are you a spammer?'),
        help_text=gettext_lazy('enter "no" if you are not a spammer'),
        widget=forms.TextInput(attrs={'size': '10'})
    )

    def __init__(self, *args, **kwargs):
        super(ThemeFormUpdate, self).__init__(*args, **kwargs)
        self.fields['theme'].choices = get_theme_choices()

    def clean_themefile(self):
        f = self.cleaned_data['themefile']
        if f.size > 512*1024:
            raise forms.ValidationError(gettext_lazy('Theme file too big.'))
        props = Theme.get_props(f.read())
        if 'name' not in props or 'weechat' not in props:
            raise forms.ValidationError(gettext_lazy('Invalid theme file.'))
        theme = Theme.objects.get(id=self.cleaned_data['theme'])
        if not theme:
            raise forms.ValidationError(gettext_lazy('Internal error.'))
        if props['name'] != theme.name:
            raise forms.ValidationError(
                gettext_lazy('Invalid name: different from theme.'))
        release_stable = Release.objects.get(version='stable')
        release_devel = Release.objects.get(version='devel')
        if props['weechat'] not in (release_stable.description,
                                    re.sub('-.*', '',
                                           release_devel.description)):
            raise forms.ValidationError(
                gettext_lazy('Invalid WeeChat version, too old!'))
        f.seek(0)
        return f


def xml_value(key, value):
    return '<%s>%s</%s>' % (
        key, value.replace('<', '&lt;').replace('>', '&gt;'), key)


def json_value(key, value):
    return '"%s": "%s",' % (
        key, value.replace('"', '\\"').replace("'", "\\'"))


def handler_theme_saved(sender, **kwargs):
    theme_list = Theme.objects.filter(visible=1).order_by('id')
    xml = '<?xml version="1.0" encoding="utf-8"?>\n'
    xml += '<themes>\n'
    json = '[\n'
    for theme in theme_list:
        if theme.visible:
            xml += '  <theme id="%s">\n' % theme.id
            json += '  {\n'
            json += '    "id": "%s",\n' % theme.id
            for key, value in theme.__dict__.items():
                if key not in ['_state', 'id', 'visible', 'approval']:
                    if value is None:
                        value = ''
                    else:
                        if key == 'mail':
                            value = value.replace('@', ' [at] ')
                            value = value.replace('.', ' [dot] ')
                        elif key == 'md5sum':
                            try:
                                with open(files_path_join(theme.path(),
                                                          theme.name),
                                          'rb') as f:
                                    filemd5 = md5()
                                    filemd5.update(f.read())
                                    value = filemd5.hexdigest()
                            except:
                                value = ''
                        elif key.startswith('desc'):
                            value = escape(value)
                    strvalue = '%s' % value
                    xml += '    %s\n' % xml_value(key, strvalue)
                    json += '    %s\n' % json_value(key, strvalue)
            # FIXME: use the "Host" from request, but...
            # request is not available in this handler!
            strvalue = 'http://www.weechat.org/%s' % theme.build_url()[1:]
            xml += '    %s\n' % xml_value('url', strvalue)
            json += '    %s\n' % json_value('url', strvalue)
            xml += '  </theme>\n'
            json += '  },\n'
    xml += '</themes>\n'
    json = json[:-2]
    json += '\n]\n'

    # create themes.xml
    filename = files_path_join('themes.xml')
    with open(filename, 'w') as f:
        f.write(xml.encode('utf-8'))

    # create themes.xml.gz
    with open(filename, 'rb') as f_in:
        f_out = gzip.open(filename + '.gz', 'wb')
        f_out.writelines(f_in)
        f_out.close()

    # create themes.json
    filename = files_path_join('themes.json')
    with open(filename, 'w') as f:
        f.write(json.encode('utf-8'))

    # create themes.json.gz
    with open(filename, 'rb') as f_in:
        f_out = gzip.open(filename + '.gz', 'wb')
        f_out.writelines(f_in)
        f_out.close()

    # create themes.tar.bz2 (with theme.xml + 'themes' directory)
    chdir(settings.FILES_ROOT)
    tar = tarfile.open(files_path_join('themes.tar.bz2'), 'w:bz2')
    tar.add('themes.xml')
    for name in listdir(files_path_join('themes')):
        if name.endswith('.theme'):
            tar.add('themes/%s' % name)
    tar.close()

post_save.connect(handler_theme_saved, sender=Theme)