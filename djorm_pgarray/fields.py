# -*- coding: utf-8 -*-

import json

import django
from django import forms
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import six
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _


TYPES = {
    "int": int,
    "smallint": int,
    "bigint": int,
    "text": force_text,
    "double precision": float,
    "varchar": force_text,
}


def _cast_to_unicode(data):
    if isinstance(data, (list, tuple)):
        return [_cast_to_unicode(x) for x in data]
    elif isinstance(data, str):
        return force_text(data)
    return data


def _cast_to_type(data, type_cast):
    if isinstance(data, (list, tuple)):
        return [_cast_to_type(x, type_cast) for x in data]
    if type_cast == str:
        return force_text(data)
    return type_cast(data)


def _unserialize(value):
    if not isinstance(value, six.string_types):
        return _cast_to_unicode(value)
    try:
        return _cast_to_unicode(json.loads(value))
    except ValueError:
        return _cast_to_unicode(value)


class ArrayField(six.with_metaclass(models.SubfieldBase, models.Field)):
    def __init__(self, *args, **kwargs):
        self._array_type = kwargs.pop("dbtype", "int")
        type_key = self._array_type.split("(")[0]

        self._explicit_type_cast = False
        if "type_cast" in kwargs:
            self._type_cast = kwargs.pop("type_cast")
            self._explicit_type_cast = True
        elif type_key in TYPES:
            self._type_cast = TYPES[type_key]
        else:
            self._type_cast = lambda x: x

        self._dimension = kwargs.pop("dimension", 1)
        kwargs.setdefault("blank", True)
        kwargs.setdefault("null", True)
        kwargs.setdefault("default", None)
        super(ArrayField, self).__init__(*args, **kwargs)

    def get_db_prep_lookup(self, lookup_type, value, connection, prepared=False):
        if lookup_type == 'contains':
            return [self.get_prep_value(value)]
        return super(ArrayField, self).get_db_prep_lookup(lookup_type, value, connection, prepared)

    def formfield(self, **params):
        params.setdefault('form_class', ArrayFormField)

        # Django 1.5 does not support "choices_form_class" parameter
        if django.VERSION[:2] >= (1, 6):
            params.setdefault('choices_form_class', forms.TypedMultipleChoiceField)
            if self.choices:
                params.setdefault('choices', self.get_choices(include_blank=False))
                params.setdefault('coerce', self._type_cast)

        return super(ArrayField, self).formfield(**params)

    def get_db_prep_value(self, value, connection, prepared=False):
        value = value if prepared else self.get_prep_value(value)
        if not value or isinstance(value, six.string_types):
            return value
        return _cast_to_type(value, self._type_cast)

    def get_prep_value(self, value):
        return value

    def to_python(self, value):
        return _unserialize(value)

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return json.dumps(self.get_prep_value(value),
                          cls=DjangoJSONEncoder)

    def validate(self, value, model_instance):
        for val in value:
            super(ArrayField, self).validate(val, model_instance)

    def deconstruct(self):
        name, path, args, kwargs = super(ArrayField, self).deconstruct()
        if self._array_type != "int":
            kwargs["dbtype"] = self._array_type
        if self._dimension != 1:
            kwargs["dimension"] = self._dimension
        if self._explicit_type_cast:
            kwargs["type_cast"] = self._type_cast
        if self.blank:
            kwargs.pop("blank", None)
        else:
            kwargs["blank"] = self.blank
        if self.null:
            kwargs.pop("null", None)
        else:
            kwargs["null"] = self.null
        if self.default is None:
            kwargs.pop("default", None)
        else:
            kwargs["default"] = self.default

        return name, path, args, kwargs

    def db_type(self, connection):
        return "{0}{1}".format(self._array_type, "[]" * self._dimension)

    def get_transform(self, name):
        transform = super(ArrayField, self).get_transform(name)

        if transform:
            return transform
        try:
            index = int(name)
        except ValueError:
            pass
        else:
            index += 1  # postgres uses 1-indexing
            return IndexTransformFactory(index, self)
        try:
            start, end = name.split('_')
            start = int(start) + 1
            end = int(end)  # don't add one here because postgres slices are weird
        except ValueError:
            pass
        else:
            return SliceTransformFactory(start, end)

class IntegerArrayField(ArrayField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dbtype", "int")
        super(IntegerArrayField, self).__init__(*args, **kwargs)


class SmallIntegerArrayField(ArrayField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dbtype", "smallint")
        super(SmallIntegerArrayField, self).__init__(*args, **kwargs)


class BigIntegerArrayField(ArrayField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dbtype", "bigint")
        super(BigIntegerArrayField, self).__init__(*args, **kwargs)


class TextArrayField(ArrayField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dbtype", "text")
        super(TextArrayField, self).__init__(*args, **kwargs)


class FloatArrayField(ArrayField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dbtype", "double precision")
        super(FloatArrayField, self).__init__(*args, **kwargs)


class DateArrayField(ArrayField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dbtype", "date")
        super(DateArrayField, self).__init__(*args, **kwargs)


class DateTimeArrayField(ArrayField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("dbtype", "timestamp with time zone")
        super(DateTimeArrayField, self).__init__(*args, **kwargs)


class ArrayFormField(forms.Field):
    default_error_messages = {
        "invalid": _("Enter a list of values, joined by commas.  E.g. \"a,b,c\"."),
    }

    def __init__(self, max_length=None, min_length=None, delim=None,
                 strip=True, *args, **kwargs):
        if delim is not None:
            self.delim = delim
        else:
            self.delim = u","

        self.strip = strip

        super(ArrayFormField, self).__init__(*args, **kwargs)

    def clean(self, value):
        if not value:
            return []

        # If Django already parsed value to list
        if isinstance(value, list):
            return value

        try:
            value = value.split(self.delim)
            if self.strip:
                value = [x.strip() for x in value]
        except Exception:
            raise ValidationError(self.error_messages["invalid"])

        return value

    def prepare_value(self, value):
        if value:
            return self.delim.join(force_text(v) for v in value)

        return super(ArrayFormField, self).prepare_value(value)

    def to_python(self, value):
        return value.split(self.delim)



if django.VERSION[:2] >= (1, 7):
    from django.db.models import Lookup, Transform

    class ContainsLookup(Lookup):
        lookup_name = "contains"

        def as_sql(self, qn, connection):
            lhs, lhs_params = self.process_lhs(qn, connection)
            rhs, rhs_params = self.process_rhs(qn, connection)
            params = lhs_params + rhs_params
            return "%s @> %s" % (lhs, rhs), params

    class ContainedByLookup(Lookup):
        lookup_name = "contained_by"

        def as_sql(self, qn, connection):
            lhs, lhs_params = self.process_lhs(qn, connection)
            rhs, rhs_params = self.process_rhs(qn, connection)
            params = lhs_params + rhs_params
            return "%s <@ %s" % (lhs, rhs), params

    class OverlapLookup(Lookup):
        lookup_name = "overlap"

        def as_sql(self, qn, connection):
            lhs, lhs_params = self.process_lhs(qn, connection)
            rhs, rhs_params = self.process_rhs(qn, connection)
            params = lhs_params + rhs_params
            return "%s && %s" % (lhs, rhs), params


    class ArrayLenTransform(Transform):
        lookup_name = 'len'

        @property
        def output_type(self):
            return models.IntegerField()

        def as_sql(self, qn, connection):
            lhs, params = qn.compile(self.lhs)
            return 'array_length(%s, 1)' % lhs, params


    ArrayField.register_lookup(ContainedByLookup)
    ArrayField.register_lookup(ContainsLookup)
    ArrayField.register_lookup(OverlapLookup)
    ArrayField.register_lookup(ArrayLenTransform)

    class IndexTransform(Transform):
        def __init__(self, index, field, *args, **kwargs):
            super(IndexTransform, self).__init__(*args, **kwargs)
            self.index = index
            self.field = field

        def as_sql(self, qn, connection):
            lhs, params = qn.compile(self.lhs)
            return '%s[%s]' % (lhs, self.index), params

        # TODO: Temporary not supported nested index lookup
        # @property
        # def output_type(self):
        #     output_type = self.field.__class__(dimension=self.field._dimension-1)
        #     output_type._array_type = self.field._array_type
        #     output_type._explicit_type_cast = self.field._explicit_type_cast
        #     output_type._type_cast = self.field._type_cast
        #     output_type.set_attributes_from_name(self.field.name)
        #     return output_type


    class SliceTransform(Transform):
        def __init__(self, start, end, *args, **kwargs):
            super(SliceTransform, self).__init__(*args, **kwargs)
            self.start = start
            self.end = end

        def as_sql(self, qn, connection):
            lhs, params = qn.compile(self.lhs)
            return '%s[%s:%s]' % (lhs, self.start, self.end), params


    class IndexTransformFactory(object):
        def __init__(self, index, field):
            self.index = index
            self.field = field

        def __call__(self, *args, **kwargs):
            return IndexTransform(self.index, self.field, *args, **kwargs)


    class SliceTransformFactory(object):
        def __init__(self, start, end):
            self.start = start
            self.end = end

        def __call__(self, *args, **kwargs):
            return SliceTransform(self.start, self.end, *args, **kwargs)



# South support
try:
    from south.modelsinspector import add_introspection_rules
    add_introspection_rules([
        (
            [ArrayField], # class
            [],           # positional params
            {
                "dbtype": ["_array_type", {"default": "int"}],
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ["^djorm_pgarray\.fields\.ArrayField"])
    add_introspection_rules([
        (
            [TextArrayField], # class
            [],           # positional params
            {
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ["^djorm_pgarray\.fields\.TextArrayField"])
    add_introspection_rules([
        (
            [FloatArrayField], # class
            [],           # positional params
            {
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ["^djorm_pgarray\.fields\.FloatArrayField"])
    add_introspection_rules([
        (
            [IntegerArrayField], # class
            [],           # positional params
            {
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ["^djorm_pgarray\.fields\.IntegerArrayField"])
    add_introspection_rules([
        (
            [BigIntegerArrayField], # class
            [],           # positional params
            {
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ["^djorm_pgarray\.fields\.BigIntegerArrayField"])
    add_introspection_rules([
        (
            [SmallIntegerArrayField], # class
            [],           # positional params
            {
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ["^djorm_pgarray\.fields\.SmallIntegerArrayField"])
    add_introspection_rules([
        (
            [DateTimeArrayField], # class
            [],           # positional params
            {
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ["^djorm_pgarray\.fields\.DateTimeArrayField"])
    add_introspection_rules([
        (
            [DateArrayField], # class
            [],           # positional params
            {
                "dimension": ["_dimension", {"default": 1}],
            }
        )
    ], ["^djorm_pgarray\.fields\.DateArrayField"])
except ImportError:
    pass
