# coding: utf-8

"""
ASN.1 type classes for universal types. Exports the following items:

 - Any()
 - Asn1Value()
 - BitString()
 - BMPString()
 - Boolean()
 - CharacterString()
 - Choice()
 - EmbeddedPdv()
 - Enumerated()
 - GeneralizedTime()
 - GeneralString()
 - GraphicString()
 - IA5String()
 - InstanceOf()
 - Integer()
 - IntegerBitString()
 - IntegerOctetString()
 - Null()
 - NumericString()
 - ObjectDescriptor()
 - ObjectIdentifier()
 - OctetBitString()
 - OctetString()
 - PrintableString()
 - Real()
 - RelativeOid()
 - Sequence()
 - SequenceOf()
 - Set()
 - SetOf()
 - TeletexString()
 - UniversalString()
 - UTCTime()
 - UTF8String()
 - VideotexString()
 - VisibleString()
 - VOID
 - Void()

Other type classes are defined that help compose the types listed above.
"""

from __future__ import unicode_literals, division, absolute_import, print_function

from datetime import datetime, timedelta
import binascii
import copy
import math
import re
import sys

from . import _teletex_codec
from ._errors import unwrap
from ._ordereddict import OrderedDict
from ._types import type_name, str_cls, byte_cls, int_types
from .util import int_to_bytes, int_from_bytes, timezone

# Python 2
if sys.version_info <= (3,):
    from cStringIO import StringIO as BytesIO

    range = xrange  # noqa
    py2 = True
    chr_cls = chr

# Python 3
else:
    from io import BytesIO

    py2 = False

    def chr_cls(num):
        return bytes([num])


_teletex_codec.register()


CLASS_NUM_TO_NAME_MAP = {
    0: 'universal',
    1: 'application',
    2: 'context',
    3: 'private',
}

CLASS_NAME_TO_NUM_MAP = {
    'universal': 0,
    'application': 1,
    'context': 2,
    'private': 3,
    0: 0,
    1: 1,
    2: 2,
    3: 3,
}

METHOD_NUM_TO_NAME_MAP = {
    0: 'primitive',
    1: 'constructed',
}


# A global tracker to ensure that _setup() is called for every class, even
# if is has been called for a parent class. This allows different _fields
# definitions for child classes. Without such a construct, the child classes
# would just see the parent class attributes and would use them.
_SETUP_CLASSES = {}


class Asn1Value(object):
    """
    The basis of all ASN.1 values
    """

    # The integer 0 for primitive, 1 for constructed
    method = None

    # An integer 0 through 3 - see CLASS_NUM_TO_NAME_MAP for value
    class_ = None

    # An integer 1 or greater indicating the tag number
    tag = None

    # A unicode string or None - "explicit" or "implicit" for
    # tagged values, None for normal
    tag_type = None

    # If "explicit"ly tagged, the class and tag for the wrapped header
    explicit_class = None
    explicit_tag = None

    # The BER/DER header bytes
    _header = None

    # Raw encoded value bytes not including class, method, tag, length header
    contents = None

    # The BER/DER trailer bytes
    _trailer = b''

    # The native python representation of the value
    _native = None

    @classmethod
    def load(cls, encoded_data, **kwargs):
        """
        Loads a BER/DER-encoded byte string using the current class as the spec

        :param encoded_data:
            A byte string of BER or DER encoded data

        :return:
            A instance of the current class
        """

        spec = None
        if cls.tag is not None:
            spec = cls

        value, _ = _parse_build(encoded_data, spec=spec, spec_params=kwargs)
        return value

    def __init__(self, tag_type=None, class_=None, tag=None, optional=None, default=None, contents=None):
        """
        The optional parameter is not used, but rather included so we don't
        have to delete it from the parameter dictionary when passing as keyword
        args

        :param tag_type:
            None for normal values, or one of "implicit", "explicit" for tagged
            values

        :param class_:
            The class for the value - defaults to "universal" if tag_type is
            None, otherwise defaults to "context". Valid values include:
             - "universal"
             - "application"
             - "context"
             - "private"

        :param tag:
            The integer tag to override - usually this is used with tag_type or
            class_

        :param optional:
            Dummy parameter that allows "optional" key in spec param dicts

        :param default:
            The default value to use if the value is currently None

        :param contents:
            A byte string of the encoded contents of the value

        :raises:
            ValueError - when tag_type, class_ or tag are invalid values
        """

        try:
            if self.__class__ not in _SETUP_CLASSES:
                cls = self.__class__
                if hasattr(cls, '_setup'):
                    self._setup()
                _SETUP_CLASSES[cls] = True

            if tag_type is not None:
                if tag_type not in ('implicit', 'explicit'):
                    raise ValueError(unwrap(
                        '''
                        tag_type must be one of "implicit", "explicit", not %s
                        ''',
                        repr(tag_type)
                    ))
                self.tag_type = tag_type

                if class_ is None:
                    class_ = 'context'
                if class_ not in CLASS_NAME_TO_NUM_MAP:
                    raise ValueError(unwrap(
                        '''
                        class_ must be one of "universal", "application",
                        "context", "private", not %s
                        ''',
                        repr(class_)
                    ))
                class_ = CLASS_NAME_TO_NUM_MAP[class_]

                if tag is not None:
                    if not isinstance(tag, int_types):
                        raise TypeError(unwrap(
                            '''
                            tag must be an integer, not %s
                            ''',
                            type_name(tag)
                        ))

                if tag_type == 'implicit':
                    self.class_ = class_
                    self.tag = tag
                else:
                    self.explicit_class = class_
                    self.explicit_tag = tag
            else:
                if class_ is not None:
                    if class_ not in CLASS_NUM_TO_NAME_MAP:
                        raise ValueError(unwrap(
                            '''
                            class_ must be one of "universal", "application",
                            "context", "private", not %s
                            ''',
                            repr(class_)
                        ))
                    self.class_ = CLASS_NAME_TO_NUM_MAP[class_]

                if tag is not None:
                    self.tag = tag

            if contents is not None:
                self.contents = contents

            elif default is not None:
                self.set(default)

        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while constructing %s' % type_name(self),) + args
            raise e

    def __str__(self):
        """
        Since str is differnt in Python 2 and 3, this calls the appropriate
        method, __unicode__() or __bytes__()

        :return:
            A unicode string
        """

        if py2:
            return self.__bytes__()
        else:
            return self.__unicode__()

    def __repr__(self):
        """
        :return:
            A unicode string
        """

        return '<%s %s %s>' % (type_name(self), id(self), repr(self.contents or b''))

    def _new_instance(self):
        """
        Constructs a new copy of the current object, preserving any tagging

        :return:
            An Asn1Value object
        """

        new_obj = self.__class__()
        new_obj.tag_type = self.tag_type
        new_obj.class_ = self.class_
        new_obj.tag = self.tag
        new_obj.explicit_class = self.explicit_class
        new_obj.explicit_tag = self.explicit_tag
        return new_obj

    def __copy__(self):
        """
        Implements the copy.copy() interface

        :return:
            A new shallow copy of the current Asn1Value object
        """

        new_obj = self._new_instance()
        new_obj._copy(self, copy.copy)
        return new_obj

    def __deepcopy__(self, memo):
        """
        Implements the copy.deepcopy() interface

        :param memo:
            A dict for memoization

        :return:
            A new deep copy of the current Asn1Value object
        """

        new_obj = self._new_instance()
        memo[id(self)] = new_obj
        new_obj._copy(self, copy.deepcopy)
        return new_obj

    def copy(self):
        """
        Copies the object, preserving any special tagging from it

        :return:
            An Asn1Value object
        """

        return copy.deepcopy(self)

    def retag(self, tag_type, tag):
        """
        Copies the object, applying a new tagging to it

        :param tag_type:
            A unicode string of "implicit" or "explicit"

        :param tag:
            A integer tag number

        :return:
            An Asn1Value object
        """

        new_obj = self.__class__(tag_type=tag_type, tag=tag)
        new_obj._copy(self, copy.deepcopy)
        return new_obj

    def untag(self):
        """
        Copies the object, removing any special tagging from it

        :return:
            An Asn1Value object
        """

        new_obj = self.__class__()
        new_obj._copy(self, copy.deepcopy)
        return new_obj

    def _copy(self, other, copy_func):
        """
        Copies the contents of another Asn1Value object to itself

        :param object:
            Another instance of the same class

        :param copy_func:
            An reference of copy.copy() or copy.deepcopy() to use when copying
            lists, dicts and objects
        """

        if self.__class__ != other.__class__:
            raise TypeError(unwrap(
                '''
                Can not copy values from %s object to %s object
                ''',
                type_name(other),
                type_name(self)
            ))

        self.contents = other.contents
        self._native = copy_func(other._native)
        if hasattr(other, '_parsed'):
            self._parsed = copy_func(other._parsed)

    def debug(self, nest_level=1):
        """
        Show the binary data and parsed data in a tree structure
        """

        prefix = '  ' * nest_level
        _basic_debug(prefix, self)
        if hasattr(self, 'parsed'):
            self.parsed.debug(nest_level + 2)
        elif hasattr(self, 'chosen'):
            self.chosen.debug(nest_level + 2)
        else:
            print('%s    Native: %s' % (prefix, self.native))

    def dump(self, force=False):
        """
        Encodes the value using DER

        :param force:
            If the encoded contents already exist, clear them and regenerate
            to ensure they are in DER format instead of BER format

        :return:
            A byte string of the DER-encoded value
        """

        contents = self.contents

        if self._header is None:
            header = _dump_header(self.class_, self.method, self.tag, self.contents)
            trailer = b''

            if self.tag_type == 'explicit':
                container = Asn1Value()
                container.method = 1
                container.class_ = self.explicit_class
                container.tag = self.explicit_tag
                container.contents = header + self.contents + trailer
                # Force the container to generate the header and footer
                container.dump()
                header = container._header + header
                trailer += container._trailer

            self._header = header
            self._trailer = trailer

        return self._header + contents + self._trailer


class ValueMap():
    """
    Basic functionality that allows for mapping values from ints or OIDs to
    python unicode strings
    """

    # A dict from primitive value (int or OID) to unicode string. This needs
    # to be defined in the source code
    _map = None

    # A dict from unicode string to int/OID. This is automatically generated
    # from _map the first time it is needed
    _reverse_map = None

    def _setup(self):
        """
        Generates _reverse_map from _map
        """

        cls = self.__class__
        if cls._map is None:
            return
        cls._reverse_map = {}
        for key, value in cls._map.items():
            cls._reverse_map[value] = key


class Void(Asn1Value):
    """
    A representation of an optional value that is not present. Has .native
    property and .dump() method to be compatible with other value classes.
    """

    contents = b''

    def __eq__(self, other):
        """
        :param other:
            The other Primitive to compare to

        :return:
            A boolean
        """

        return other.__class__ == self.__class__

    def __nonzero__(self):
        return False

    def __len__(self):
        return 0

    def __iter__(self):
        return iter(())

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            None
        """

        return None

    def dump(self, force=False):
        """
        Encodes the value using DER

        :param force:
            If the encoded contents already exist, clear them and regenerate
            to ensure they are in DER format instead of BER format

        :return:
            A byte string of the DER-encoded value
        """

        return b''


VOID = Void()


class Any(Asn1Value):
    """
    A value class that can contain any value, and allows for easy parsing of
    the underlying encoded value using a spec. This is normally contained in
    a Structure that has an ObjectIdentifier field and _oid_pair and _oid_specs
    defined.
    """

    # The parsed value object
    _parsed = None

    def __init__(self, value=None, **kwargs):
        """
        Sets the value of the object before passing to Asn1Value.__init__()

        :param value:
            An Asn1Value object that will be set as the parsed value
        """

        Asn1Value.__init__(self, **kwargs)

        try:
            if value is not None:
                if not isinstance(value, Asn1Value):
                    raise TypeError(unwrap(
                        '''
                        value must be an instance of Ans1Value, not %s
                        ''',
                        type_name(value)
                    ))

                self._parsed = (value, value.__class__, None)
                self.contents = value.dump()

        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while constructing %s' % type_name(self),) + args
            raise e

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            The .native value from the parsed value object
        """

        if self._parsed is None:
            self.parse()

        return self._parsed[0].native

    @property
    def parsed(self):
        """
        Returns the parsed object from .parse()

        :return:
            The object returned by .parse()
        """

        if self._parsed is None:
            self.parse()

        return self._parsed[0]

    def parse(self, spec=None, spec_params=None):
        """
        Parses the contents generically, or using a spec with optional params

        :param spec:
            A class derived from Asn1Value that defines what class_ and tag the
            value should have, and the semantics of the encoded value. The
            return value will be of this type. If omitted, the encoded value
            will be decoded using the standard universal tag based on the
            encoded tag number.

        :param spec_params:
            A dict of params to pass to the spec object

        :return:
            An object of the type spec, or if not present, a child of Asn1Value
        """

        if self._parsed is None or self._parsed[1:3] != (spec, spec_params):
            try:
                passed_params = spec_params
                if self.tag_type == 'explicit':
                    passed_params = {} if not spec_params else spec_params.copy()
                    passed_params['tag_type'] = self.tag_type
                    passed_params['tag'] = self.tag
                parsed_value, _ = _parse_build(
                    self._header + self.contents + self._trailer,
                    spec=spec,
                    spec_params=passed_params
                )
                self._parsed = (parsed_value, spec, spec_params)
            except (ValueError, TypeError) as e:
                args = e.args[1:]
                e.args = (e.args[0] + '\n    while parsing %s' % type_name(self),) + args
                raise e
        return self._parsed[0]

    def dump(self, force=False):
        """
        Encodes the value using DER

        :param force:
            If the encoded contents already exist, clear them and regenerate
            to ensure they are in DER format instead of BER format

        :return:
            A byte string of the DER-encoded value
        """

        if self._parsed is None:
            self.parse()

        return self._parsed[0].dump(force=force)


class Choice(Asn1Value):
    """
    A class to handle when a value may be one of several options
    """

    # The index in _alternatives of the validated alternative
    _choice = None

    # The name of the chosen alternative
    _name = None

    # The Asn1Value object for the chosen alternative
    _parsed = None

    # A list of tuples in one of the following forms.
    #
    # Option 1, a unicode string field name and a value class
    #
    # ("name", Asn1ValueClass)
    #
    # Option 2, same as Option 1, but with a dict of class params
    #
    # ("name", Asn1ValueClass, {'tag_type': 'explicit', 'tag': 5})
    _alternatives = None

    # A dict that maps tuples of (class_, tag) to an index in _alternatives
    _id_map = None

    # A dict that maps alternative names to an index in _alternatives
    _name_map = None

    @classmethod
    def load(cls, encoded_data, **kwargs):
        """
        Loads a BER/DER-encoded byte string using the current class as the spec

        :param encoded_data:
            A byte string of BER or DER encoded data

        :return:
            A instance of the current class
        """

        value, _ = _parse_build(encoded_data, spec=cls, spec_params=kwargs)
        return value

    def _setup(self):
        """
        Generates _id_map from _alternatives to allow validating contents
        """

        cls = self.__class__
        cls._id_map = {}
        cls._name_map = {}
        for index, info in enumerate(cls._alternatives):
            if len(info) < 3:
                info = info + ({},)
                cls._alternatives[index] = info
            id_ = _build_id_tuple(info[2], info[1])
            cls._id_map[id_] = index
            cls._name_map[info[0]] = index

    def __init__(self, name=None, value=None, tag_type=None, **kwargs):
        """
        Checks to ensure implicit tagging is not being used since it is
        incompatible with Choice, then forwards on to Asn1Value.__init__()

        :param name:
            The name of the alternative to be set - used with value

        :param value:
            The alternative value to set - used with name

        :param tag_type:
            The tag_type of the value - None, "implicit" or "explicit"

        :raises:
            ValueError - when tag_type is "implicit"
        """

        kwargs['tag_type'] = tag_type
        Asn1Value.__init__(self, **kwargs)

        try:
            if tag_type == 'implicit':
                raise ValueError(unwrap(
                    '''
                    The Choice type can not be implicitly tagged even if in an
                    implicit module - due to its nature any tagging must be
                    explicit
                    '''
                ))

            if name is not None:
                if name not in self._name_map:
                    raise ValueError(unwrap(
                        '''
                        The name specified, "%s", is not a valid alternative
                        for %s
                        ''',
                        name,
                        type_name(self)
                    ))

                self._choice = self._name_map[name]
                _, spec, params = self._alternatives[self._choice]

                if not isinstance(value, spec):
                    value = spec(value, **params)
                else:
                    value = _fix_tagging(value, params)
                self._parsed = value

        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while constructing %s' % type_name(self),) + args
            raise e

    @property
    def name(self):
        """
        :return:
            A unicode string of the field name of the chosen alternative
        """
        if not self._name:
            self._name = self._alternatives[self._choice][0]
        return self._name

    def parse(self):
        """
        Parses the detected alternative

        :return:
            An Asn1Value object of the chosen alternative
        """

        if self._parsed is not None:
            return self._parsed

        try:
            _, spec, params = self._alternatives[self._choice]
            self._parsed, _ = _parse_build(self.contents, spec=spec, spec_params=params)
        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while parsing %s' % type_name(self),) + args
            raise e

    @property
    def chosen(self):
        """
        :return:
            An Asn1Value object of the chosen alternative
        """

        return self.parse()

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            The .native value from the contained value object
        """

        return self.chosen.native

    def validate(self, class_, tag, contents):
        """
        Ensures that the class and tag specified exist as an alternative

        :param class_:
            The integer class_ from the encoded value header

        :param tag:
            The integer tag from the encoded value header

        :param contents:
            A byte string of the contents of the value - used when the object
            is explicitly tagged

        :raises:
            ValueError - when value is not a valid alternative
        """

        id_ = (class_, tag)

        if self.tag_type == 'explicit':
            if (self.explicit_class, self.explicit_tag) != id_:
                raise ValueError(unwrap(
                    '''
                    %s was explicitly tagged, but the value provided does not
                    match the class and tag
                    ''',
                    type_name(self)
                ))

            ((class_, _, tag, _, _, _), _) = _parse(contents)
            id_ = (class_, tag)

        if id_ in self._id_map:
            self._choice = self._id_map[id_]
            return

        # This means the Choice was implicitly tagged
        if self.class_ is not None and self.tag is not None:
            if len(self._alternatives) > 1:
                raise ValueError(unwrap(
                    '''
                    %s was implicitly tagged, but more than one alternative
                    exists
                    ''',
                    type_name(self)
                ))
            if id_ == (self.class_, self.tag):
                self._choice = 0
                return

        asn1 = self._format_class_tag(class_, tag)
        asn1s = [self._format_class_tag(pair[0], pair[1]) for pair in self._id_map]

        raise ValueError(unwrap(
            '''
            Value %s did not match the class and tag of any of the alternatives
            in %s: %s
            ''',
            asn1,
            type_name(self),
            ', '.join(asn1s)
        ))

    def _format_class_tag(self, class_, tag):
        """
        :return:
            A unicode string of a human-friendly representation of the class and tag
        """

        return '[%s %s]' % (CLASS_NUM_TO_NAME_MAP[class_].upper(), tag)

    def _copy(self, other, copy_func):
        """
        Copies the contents of another Asn1Value object to itself

        :param object:
            Another instance of the same class

        :param copy_func:
            An reference of copy.copy() or copy.deepcopy() to use when copying
            lists, dicts and objects
        """

        if self.__class__ != other.__class__:
            raise TypeError(unwrap(
                '''
                Can not copy values from %s object to %s object
                ''',
                type_name(other),
                type_name(self)
            ))

        self.contents = other.contents
        self._native = copy_func(other._native)
        self._choice = other._choice
        self._name = other._name
        self._parsed = copy_func(other._parsed)

    def dump(self, force=False):
        """
        Encodes the value using DER

        :param force:
            If the encoded contents already exist, clear them and regenerate
            to ensure they are in DER format instead of BER format

        :return:
            A byte string of the DER-encoded value
        """

        self.contents = self.chosen.dump(force=force)
        if self._header is None:
            if self.tag_type == 'explicit':
                self._header = _dump_header(self.explicit_class, 1, self.explicit_tag, self.contents)
            else:
                self._header = b''
        return self._header + self.contents


class Primitive(Asn1Value):
    """
    Sets the class_ and method attributes for primitive, universal values
    """

    class_ = 0

    method = 0

    def __init__(self, value=None, default=None, contents=None, **kwargs):
        """
        Sets the value of the object before passing to Asn1Value.__init__()

        :param value:
            A native Python datatype to initialize the object value with

        :param default:
            The default value if no value is specified

        :param contents:
            A byte string of the encoded contents of the value
        """

        Asn1Value.__init__(self, **kwargs)

        try:
            if contents is not None:
                self.contents = contents

            elif value is not None:
                self.set(value)

            elif default is not None:
                self.set(default)

        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while constructing %s' % type_name(self),) + args
            raise e

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            A byte string
        """

        if not isinstance(value, byte_cls):
            raise TypeError(unwrap(
                '''
                %s value must be a byte string, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        self._native = value
        self.contents = value
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def dump(self, force=False):
        """
        Encodes the value using DER

        :param force:
            If the encoded contents already exist, clear them and regenerate
            to ensure they are in DER format instead of BER format

        :return:
            A byte string of the DER-encoded value
        """

        if force:
            native = self.native
            self.contents = None
            self.set(native)

        return Asn1Value.dump(self)

    def __ne__(self, other):
        return not self == other

    def __eq__(self, other):
        """
        :param other:
            The other Primitive to compare to

        :return:
            A boolean
        """

        if not isinstance(other, Primitive):
            return False

        if self.contents != other.contents:
            return False

        # We compare class tag numbers since object tag numbers could be
        # different due to implicit or explicit tagging
        if self.__class__.tag != other.__class__.tag:
            return False

        if self.__class__ == other.__class__ and self.contents == other.contents:
            return True

        # If the objects share a common base class that is not too low-level
        # then we can compare the contents
        self_bases = (set(self.__class__.__bases__) | set([self.__class__])) - set([Asn1Value, Primitive, ValueMap])
        other_bases = (set(other.__class__.__bases__) | set([other.__class__])) - set([Asn1Value, Primitive, ValueMap])
        if self_bases | other_bases:
            return self.contents == other.contents

        # When tagging is going on, do the extra work of constructing new
        # objects to see if the dumped representation are the same
        if self.tag_type is not None or other.tag_type is not None:
            return self.untag().dump() == other.untag().dump()

        return self.dump() == other.dump()


class AbstractString(Primitive):
    """
    A base class for all strings that have a known encoding. In general, we do
    not worry ourselves with confirming that the decoded values match a specific
    set of characters, only that they are decoded into a Python unicode string
    """

    # The Python encoding name to use when decoding or encoded the contents
    _encoding = 'latin1'

    def set(self, value):
        """
        Sets the value of the string

        :param value:
            A unicode string
        """

        if not isinstance(value, str_cls):
            raise TypeError(unwrap(
                '''
                %s value must be a unicode string, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        self._native = value
        self.contents = value.encode(self._encoding)
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def __unicode__(self):
        """
        :return:
            A unicode string
        """

        return self.contents.decode(self._encoding)

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            A unicode string or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            self._native = self.__unicode__()
        return self._native


class Boolean(Primitive):
    """
    Represents a boolean in both ASN.1 and Python
    """

    tag = 1

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            True, False or another value that works with bool()
        """

        self._native = bool(value)
        self.contents = b'\x00' if not value else b'\xff'
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    # Python 2
    def __nonzero__(self):
        """
        :return:
            True or False
        """
        return self.__bool__()

    def __bool__(self):
        """
        :return:
            True or False
        """
        return self.contents != b'\x00'

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            True, False or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            self._native = self.__bool__()
        return self._native


class Integer(Primitive, ValueMap):
    """
    Represents an integer in both ASN.1 and Python
    """

    tag = 2

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            An integer, or a unicode string if _map is set

        :raises:
            ValueError - when an invalid value is passed
        """

        if isinstance(value, str_cls):
            if self._map is None:
                raise ValueError(unwrap(
                    '''
                    %s value is a unicode string, but no _map provided
                    ''',
                    type_name(self)
                ))

            if value not in self._reverse_map:
                raise ValueError(unwrap(
                    '''
                    %s value, %s, is not present in the _map
                    ''',
                    type_name(self),
                    value
                ))

            value = self._reverse_map[value]

        elif not isinstance(value, int_types):
            raise TypeError(unwrap(
                '''
                %s value must be an integer or unicode string when a name_map
                is provided, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        self._native = self._map[value] if self._map and value in self._map else value

        self.contents = int_to_bytes(value, signed=True)
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def __int__(self):
        """
        :return:
            An integer
        """
        return int_from_bytes(self.contents, signed=True)

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            An integer or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            self._native = self.__int__()
            if self._map is not None and self._native in self._map:
                self._native = self._map[self._native]
        return self._native


class BitString(Primitive, ValueMap, object):
    """
    Represents a bit string from ASN.1 as a Python tuple of 1s and 0s
    """

    tag = 3

    _size = None

    def _setup(self):
        """
        Generates _reverse_map from _map
        """

        ValueMap._setup(self)

        cls = self.__class__
        if cls._map is not None:
            cls._size = max(self._map.keys()) + 1

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            An integer or a tuple of integers 0 and 1

        :raises:
            ValueError - when an invalid value is passed
        """

        if isinstance(value, set):
            if self._map is None:
                raise ValueError(unwrap(
                    '''
                    %s _map has not been defined
                    ''',
                    type_name(self)
                ))

            bits = [0] * self._size
            self._native = value
            for index in range(0, self._size):
                key = self._map.get(index)
                if key is None:
                    continue
                if key in value:
                    bits[index] = 1

            value = ''.join(map(str_cls, bits))

        elif isinstance(value, tuple):
            if self._map is None:
                self._native = value
            else:
                self._native = set()
                for index, bit in enumerate(value):
                    if bit:
                        name = self._map.get(index, index)
                        self._native.add(name)
            value = ''.join(map(str_cls, value))

        else:
            raise TypeError(unwrap(
                '''
                %s value must be a tuple of ones and zeros or a set of unicode
                strings, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        if self._map is not None:
            size = self._size
            if len(value) > size:
                raise ValueError(unwrap(
                    '''
                    %s value must be at most %s bits long, specified was %s long
                    ''',
                    type_name(self),
                    size,
                    len(value)
                ))
            value += '0' * (size - len(value))
        else:
            size = len(value)

        size_mod = size % 8
        extra_bits = 0
        if size_mod != 0:
            extra_bits = 8 - size_mod
            value += '0' * extra_bits

        size_in_bytes = int(math.ceil(size / 8))

        if extra_bits:
            extra_bits_byte = int_to_bytes(extra_bits)
        else:
            extra_bits_byte = b'\x00'

        if value == '':
            value_bytes = b''
        else:
            value_bytes = int_to_bytes(int(value, 2))
        if len(value_bytes) != size_in_bytes:
            value_bytes = (b'\x00' * (size_in_bytes - len(value_bytes))) + value_bytes

        self.contents = extra_bits_byte + value_bytes
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def __getitem__(self, key):
        """
        Retrieves a boolean version of one of the bits based on a name from the
        _map

        :param key:
            The unicode string of one of the bit names

        :raises:
            ValueError - when _map is not set or the key name is invalid

        :return:
            A boolean if the bit is set
        """

        is_int = isinstance(key, int_types)
        if not is_int:
            if not isinstance(self._map, dict):
                raise ValueError(unwrap(
                    '''
                    %s _map has not been defined
                    ''',
                    type_name(self)
                ))

            if key not in self._reverse_map:
                raise ValueError(unwrap(
                    '''
                    %s _map does not contain an entry for "%s"
                    ''',
                    type_name(self),
                    key
                ))

        if self._native is None:
            self.native

        if self._map is None:
            if len(self._native) >= key + 1:
                return bool(self._native[key])
            return False

        if is_int:
            key = self._map.get(key, key)

        return key in self._native

    def __setitem__(self, key, value):
        """
        Sets one of the bits based on a name from the _map

        :param key:
            The unicode string of one of the bit names

        :param value:
            A boolean value

        :raises:
            ValueError - when _map is not set or the key name is invalid
        """

        is_int = isinstance(key, int_types)
        if not is_int:
            if self._map is None:
                raise ValueError(unwrap(
                    '''
                    %s _map has not been defined
                    ''',
                    type_name(self)
                ))

            if key not in self._reverse_map:
                raise ValueError(unwrap(
                    '''
                    %s _map does not contain an entry for "%s"
                    ''',
                    type_name(self),
                    key
                ))

        if self._native is None:
            self.native

        if self._map is None:
            new_native = list(self._native)
            max_key = len(new_native) - 1
            if key > max_key:
                new_native.extend([0] * (key - max_key))
            new_native[key] = 1 if value else 0
            self._native = tuple(new_native)

        else:
            if is_int:
                key = self._map.get(key, key)

            if value:
                if key not in self._native:
                    self._native.add(key)
            else:
                if key in self._native:
                    self._native.remove(key)

        self.set(self._native)

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            If a _map is set, a set of names, or if no _map is set, a tuple of
            integers 1 and 0. None if no value.
        """

        # For BitString we default the value to be all zeros
        if self.contents is None:
            if self._map is None:
                self.set(())
            else:
                self.set(set())

        if self._native is None:
            extra_bits = int_from_bytes(self.contents[0:1])
            bit_string = '{0:b}'.format(int_from_bytes(self.contents[1:]))

            # Left-pad the bit string to a byte multiple to ensure we didn't
            # lose any zero bits on the left
            mod_bit_len = len(bit_string) % 8
            if mod_bit_len != 0:
                bit_string = ('0' * (8 - mod_bit_len)) + bit_string

            # Trim off the extra bits on the right used to fill the last byte
            if extra_bits > 0:
                bit_string = bit_string[0:0 - extra_bits]

            bits = tuple(map(int, tuple(bit_string)))
            if self._map:
                self._native = set()
                for index, bit in enumerate(bits):
                    if bit:
                        name = self._map.get(index, index)
                        self._native.add(name)
            else:
                self._native = bits
        return self._native


class OctetBitString(Primitive):
    """
    Represents a bit string in ASN.1 as a Python byte string
    """

    tag = 3

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            A byte string

        :raises:
            ValueError - when an invalid value is passed
        """

        if not isinstance(value, byte_cls):
            raise TypeError(unwrap(
                '''
                %s value must be a byte string, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        self._native = value
        # Set the unused bits to 0
        self.contents = b'\x00' + value
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def __bytes__(self):
        """
        :return:
            A byte string
        """

        # Whenever dealing with octet-based bit strings, we really want the
        # bytes, so we just ignore the unused bits portion since it isn't
        # applicable to the current use case
        # unused_bits = struct.unpack('>B', self.contents[0:1])[0]
        return self.contents[1:]

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            A byte string or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            self._native = self.__bytes__()
        return self._native


class IntegerBitString(Primitive):
    """
    Represents a bit string in ASN.1 as a Python integer
    """

    tag = 3

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            An integer

        :raises:
            ValueError - when an invalid value is passed
        """

        if not isinstance(value, int_types):
            raise TypeError(unwrap(
                '''
                %s value must be an integer, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        self._native = value
        # Set the unused bits to 0
        self.contents = b'\x00' + int_to_bytes(value, signed=True)
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            An integer or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            extra_bits = int_from_bytes(self.contents[0:1])
            if extra_bits > 0:
                bit_string = '{0:b}'.format(int_from_bytes(self.contents[1:]))
                bit_string = bit_string[0:0 - extra_bits]
                self._native = int(bit_string, 2)
            else:
                self._native = int_from_bytes(self.contents[1:])
        return self._native


class OctetString(Primitive):
    """
    Represents a byte string in both ASN.1 and Python
    """

    tag = 4

    def __bytes__(self):
        """
        :return:
            A byte string
        """

        return self.contents

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            A byte string or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            self._native = self.__bytes__()
        return self._native


class IntegerOctetString(Primitive):
    """
    Represents a byte string in ASN.1 as a Python integer
    """

    tag = 4

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            An integer

        :raises:
            ValueError - when an invalid value is passed
        """

        if not isinstance(value, int_types):
            raise TypeError(unwrap(
                '''
                %s value must be an integer, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        self._native = value
        # Set the unused bits to 0
        self.contents = int_to_bytes(value, signed=True)
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            An integer or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            self._native = int_from_bytes(self.contents)
        return self._native


class ParsableOctetString(Primitive):

    tag = 4

    _parsed = None

    def __init__(self, value=None, parsed=None, **kwargs):
        """
        Allows providing a parsed object that will be serialized to get the
        byte string value

        :param value:
            A native Python datatype to initialize the object value with

        :param parsed:
            If value is None and this is an Asn1Value object, this will be
            set as the parsed value, and the value will be obtained by calling
            .dump() on this object.
        """

        set_parsed = False
        if value is None and parsed is not None and isinstance(parsed, Asn1Value):
            value = parsed.dump()
            set_parsed = True

        Primitive.__init__(self, value=value, **kwargs)

        if set_parsed:
            self._parsed = (parsed, parsed.__class__, None)
            self._native = parsed.native

    def parse(self, spec=None, spec_params=None):
        """
        Parses the contents generically, or using a spec with optional params

        :param spec:
            A class derived from Asn1Value that defines what class_ and tag the
            value should have, and the semantics of the encoded value. The
            return value will be of this type. If omitted, the encoded value
            will be decoded using the standard universal tag based on the
            encoded tag number.

        :param spec_params:
            A dict of params to pass to the spec object

        :return:
            An object of the type spec, or if not present, a child of Asn1Value
        """

        if self._parsed is None or self._parsed[1:3] != (spec, spec_params):
            parsed_value, _ = _parse_build(byte_cls(self), spec=spec, spec_params=spec_params)
            self._parsed = (parsed_value, spec, spec_params)
        return self._parsed[0]

    def __bytes__(self):
        """
        :return:
            A byte string
        """

        return self.contents

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            A byte string or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            if self._parsed is not None:
                self._native = self._parsed[0].native
            else:
                self._native = self.__bytes__()
        return self._native

    @property
    def parsed(self):
        """
        Returns the parsed object from .parse()

        :return:
            The object returned by .parse()
        """

        if self._parsed is None:
            self.parse()

        return self._parsed[0]

    def _copy(self, other, copy_func):
        """
        Copies the contents of another ParsableOctetString object to itself

        :param object:
            Another instance of the same class

        :param copy_func:
            An reference of copy.copy() or copy.deepcopy() to use when copying
            lists, dicts and objects
        """

        if self.__class__ != other.__class__:
            raise TypeError(unwrap(
                '''
                Can not copy values from %s object to %s object
                ''',
                type_name(other),
                type_name(self)
            ))

        self.contents = other.contents
        self._native = copy_func(other._native)
        self._parsed = copy_func(other._parsed)

    def dump(self, force=False):
        """
        Encodes the value using DER

        :param force:
            If the encoded contents already exist, clear them and regenerate
            to ensure they are in DER format instead of BER format

        :return:
            A byte string of the DER-encoded value
        """

        if force:
            if self._parsed is not None:
                native = self.parsed.dump(force=force)
            else:
                native = self.native
            self.contents = None
            self.set(native)

        return Asn1Value.dump(self)


class ParsableOctetBitString(ParsableOctetString):

    tag = 3

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            A byte string

        :raises:
            ValueError - when an invalid value is passed
        """

        if not isinstance(value, byte_cls):
            raise TypeError(unwrap(
                '''
                %s value must be a byte string, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        self._native = value
        # Set the unused bits to 0
        self.contents = b'\x00' + value
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def __bytes__(self):
        """
        :return:
            A byte string
        """

        # Whenever dealing with octet-based bit strings, we really want the
        # bytes, so we just ignore the unused bits portion since it isn't
        # applicable to the current use case
        # unused_bits = struct.unpack('>B', self.contents[0:1])[0]
        return self.contents[1:]


class Null(Primitive):
    """
    Represents a null value in ASN.1 as None in Python
    """

    tag = 5

    contents = b''

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            None
        """

        self.contents = b''

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            None
        """

        return None


class ObjectIdentifier(Primitive, ValueMap):
    """
    Represents an object identifier in ASN.1 as a Python unicode dotted
    integer string
    """

    tag = 6

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            A unicode string. May be a dotted integer string, or if _map is
            provided, one of the mapped values.

        :raises:
            ValueError - when an invalid value is passed
        """

        if not isinstance(value, str_cls):
            raise TypeError(unwrap(
                '''
                %s value must be a unicode string, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        self._native = value

        if self._map is not None:
            if value in self._reverse_map:
                value = self._reverse_map[value]

        self.contents = b''
        first = None
        for index, part in enumerate(value.split('.')):
            part = int(part)

            # The first two parts are merged into a single byte
            if index == 0:
                first = part
                continue
            elif index == 1:
                part = (first * 40) + part

            encoded_part = chr_cls(0x7F & part)
            part = part >> 7
            while part > 0:
                encoded_part = chr_cls(0x80 | (0x7F & part)) + encoded_part
                part = part >> 7
            self.contents += encoded_part

        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def __unicode__(self):
        """
        :return:
            A unicode string
        """
        output = []

        part = 0
        for byte in self.contents:
            if py2:
                byte = ord(byte)
            part = part * 128
            part += byte & 127
            # Last byte in subidentifier has the eighth bit set to 0
            if byte & 0x80 == 0:
                if len(output) == 0:
                    output.append(str_cls(part // 40))
                    output.append(str_cls(part % 40))
                else:
                    output.append(str_cls(part))
                part = 0

        return '.'.join(output)

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            A unicode string or None. If _map is not defined, the unicode string
            is a string of dotted integers. If _map is defined and the dotted
            string is present in the _map, the mapped value is returned.
        """

        if self.contents is None:
            return None

        if self._native is None:
            self._native = self.__unicode__()
            if self._map is not None and self._native in self._map:
                self._native = self._map[self._native]
        return self._native


class ObjectDescriptor(Primitive):
    """
    Represents an object descriptor from ASN.1 - no Python implementation
    """

    tag = 7


class InstanceOf(Primitive):
    """
    Represents an instance from ASN.1 - no Python implementation
    """

    tag = 8


class Real(Primitive):
    """
    Represents a real number from ASN.1 - no Python implementation
    """

    tag = 9


class Enumerated(Integer):
    """
    Represents a enumerated list of integers from ASN.1 as a Python
    unicode string
    """

    tag = 10

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            An integer or a unicode string from _map

        :raises:
            ValueError - when an invalid value is passed
        """

        if not isinstance(value, int_types) and not isinstance(value, str_cls):
            raise TypeError(unwrap(
                '''
                %s value must be an integer or a unicode string, not %s
                ''',
                type_name(self),
                type_name(value)
            ))

        if isinstance(value, str_cls):
            if value not in self._reverse_map:
                raise ValueError(unwrap(
                    '''
                    %s value "%s" is not a valid value
                    ''',
                    type_name(self),
                    value
                ))

            value = self._reverse_map[value]

        elif value not in self._map:
            raise ValueError(unwrap(
                '''
                %s value %s is not a valid value
                ''',
                type_name(self),
                value
            ))

        Integer.set(self, value)

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            A unicode string or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            self._native = self._map[self.__int__()]
        return self._native


class UTF8String(AbstractString):
    """
    Represents a UTF-8 string from ASN.1 as a Python unicode string
    """

    tag = 12
    _encoding = 'utf-8'


class RelativeOid(ObjectIdentifier):
    """
    Represents an object identifier in ASN.1 as a Python unicode dotted
    integer string
    """

    tag = 13


class Sequence(Asn1Value):
    """
    Represents a sequence of fields from ASN.1 as a Python object with a
    dict-like interface
    """

    tag = 16

    class_ = 0
    method = 1

    # A list of child objects, in order of _fields
    children = None

    # Sequence overrides .contents to be a property so that the mutated state
    # of child objects can be checked to ensure everything is up-to-date
    _contents = None

    # Variable to track if the object has been mutated
    _mutated = False

    # A list of tuples in one of the following forms.
    #
    # Option 1, a unicode string field name and a value class
    #
    # ("name", Asn1ValueClass)
    #
    # Option 2, same as Option 1, but with a dict of class params
    #
    # ("name", Asn1ValueClass, {'tag_type': 'explicit', 'tag': 5})
    _fields = []

    # A dict with keys being the name of a field and the value being a unicode
    # string of the method name on self to call to get the spec for that field
    _spec_callbacks = None

    # A dict that maps unicode string field names to an index in _fields
    _field_map = None

    # A list in the same order as _fields that has tuples in the form (class_, tag)
    _field_ids = None

    # An optional 2-element tuple that defines the field names of an OID field
    # and the field that the OID should be used to help decode. Works with the
    # _oid_specs attribute.
    _oid_pair = None

    # A dict with keys that are unicode string OID values and values that are
    # Asn1Value classes to use for decoding a variable-type field.
    _oid_specs = None

    # A 2-element tuple of the indexes in _fields of the OID and value fields
    _oid_nums = None

    def __init__(self, value=None, default=None, **kwargs):
        """
        Allows setting field values before passing everything else along to
        Asn1Value.__init__()

        :param value:
            A native Python datatype to initialize the object value with

        :param default:
            The default value if no value is specified
        """

        Asn1Value.__init__(self, **kwargs)

        check_existing = False
        if value is None and default is not None:
            check_existing = True
            if self.children is None:
                if self.contents is None:
                    check_existing = False
                else:
                    self._parse_children()
            value = default

        if value is not None:
            try:
                # Fields are iterated in definition order to allow things like
                # OID-based specs. Otherwise sometimes the value would be processed
                # before the OID field, resulting in invalid value object creation.
                if self._fields:
                    keys = [info[0] for info in self._fields]
                else:
                    keys = value.keys()

                for key in keys:
                    # If we are setting defaults, but a real value has already
                    # been set for the field, then skip it
                    if check_existing:
                        index = self._field_map[key]
                        if index < len(self.children) and self.children[index] is not VOID:
                            continue

                    if key in value:
                        self.__setitem__(key, value[key])

            except (ValueError, TypeError) as e:
                args = e.args[1:]
                e.args = (e.args[0] + '\n    while constructing %s' % type_name(self),) + args
                raise e

    @property
    def contents(self):
        """
        :return:
            A byte string of the DER-encoded contents of the sequence
        """

        if self.children is None:
            return self._contents

        if self._is_mutated():
            self._set_contents()

        return self._contents

    @contents.setter
    def contents(self, value):
        """
        :param value:
            A byte string of the DER-encoded contents of the sequence
        """

        self._contents = value

    def _is_mutated(self):
        """
        :return:
            A boolean - if the sequence or any children (recursively) have been
            mutated
        """

        mutated = self._mutated
        if self.children is not None:
            for child in self.children:
                if isinstance(child, Sequence) or isinstance(child, SequenceOf):
                    mutated = mutated or child._is_mutated()

        return mutated

    def _lazy_child(self, index):
        """
        Builds a child object if the child has only been parsed into a tuple so far
        """

        child = self.children[index]
        if isinstance(child, tuple):
            child = _build(*child)
            self.children[index] = child
        return child

    def __len__(self):
        """
        :return:
            Integer
        """
        # We inline this check to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        return len(self.children)

    def __getitem__(self, key):
        """
        Allows accessing fields by name or index

        :param key:
            A unicode string of the field name, or an integer of the field index

        :raises:
            ValueError - when a field name or index is invalid

        :return:
            The Asn1Value object of the field specified
        """

        # We inline this check to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        if not isinstance(key, int_types):
            if key not in self._field_map:
                raise KeyError(unwrap(
                    '''
                    No field named "%s" defined for %s
                    ''',
                    key,
                    type_name(self)
                ))
            key = self._field_map[key]

        if key >= len(self.children):
            raise KeyError(unwrap(
                '''
                No field numbered %s is present in this %s
                ''',
                key,
                type_name(self)
            ))

        try:
            return self._lazy_child(key)

        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while parsing %s' % type_name(self),) + args
            raise e

    def __setitem__(self, key, value):
        """
        Allows settings fields by name or index

        :param key:
            A unicode string of the field name, or an integer of the field index

        :param value:
            A native Python datatype to set the field value to. This method will
            construct the appropriate Asn1Value object from _fields.

        :raises:
            ValueError - when a field name or index is invalid
        """

        # We inline this check to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        if not isinstance(key, int_types):
            if key not in self._field_map:
                raise KeyError(unwrap(
                    '''
                    No field named "%s" defined for %s
                    ''',
                    key,
                    type_name(self)
                ))
            key = self._field_map[key]

        field_name, field_spec, value_spec, field_params, _ = self._determine_spec(key)

        new_value = self._make_value(field_name, field_spec, value_spec, field_params, value)

        invalid_value = False
        if isinstance(new_value, Any):
            invalid_value = new_value.parsed is None
        elif isinstance(new_value, Choice):
            invalid_value = new_value.chosen.contents is None
        else:
            invalid_value = new_value.contents is None

        if invalid_value:
            raise ValueError(unwrap(
                '''
                Value for field "%s" of %s is not set
                ''',
                field_name,
                type_name(self)
            ))

        self.children[key] = new_value

        if self._native is not None:
            self._native[self._fields[key][0]] = self.children[key].native
        self._mutated = True

    def __delitem__(self, key):
        """
        Allows deleting optional or default fields by name or index

        :param key:
            A unicode string of the field name, or an integer of the field index

        :raises:
            ValueError - when a field name or index is invalid, or the field is not optional or defaulted
        """

        # We inline this check to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        if not isinstance(key, int_types):
            if key not in self._field_map:
                raise KeyError(unwrap(
                    '''
                    No field named "%s" defined for %s
                    ''',
                    key,
                    type_name(self)
                ))
            key = self._field_map[key]

        name, _, params = self._fields[key]
        if not params or ('default' not in params and 'optional' not in params):
            raise ValueError(unwrap(
                '''
                Can not delete the value for the field "%s" of %s since it is
                not optional or defaulted
                ''',
                name,
                type_name(self)
            ))

        if 'optional' in params:
            self.children[key] = VOID
            if self._native is not None:
                self._native[name] = None
        else:
            self.__setitem__(key, None)
        self._mutated = True

    def __iter__(self):
        """
        :return:
            An iterator of field key names
        """

        for info in self._fields:
            yield info[0]

    def _set_contents(self, force=False):
        """
        Updates the .contents attribute of the value with the encoded value of
        all of the child objects

        :param force:
            Ensure all contents are in DER format instead of possibly using
            cached BER-encoded data
        """

        if self.children is None:
            self._parse_children()

        contents = BytesIO()
        for index, info in enumerate(self._fields):
            child = self.children[index]
            if child is None:
                child_dump = b''
            elif isinstance(child, tuple):
                if force:
                    child_dump = self._lazy_child(index).dump(force=force)
                else:
                    child_dump = child[3] + child[4] + child[5]
            else:
                child_dump = child.dump(force=force)
            # Skip values that are the same as the default
            if info[2] and 'default' in info[2]:
                default_value = info[1](**info[2])
                if default_value.dump() == child_dump:
                    continue
            contents.write(child_dump)
        self._contents = contents.getvalue()

        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def _setup(self):
        """
        Generates _field_map, _field_ids and _oid_nums for use in parsing
        """

        cls = self.__class__
        cls._field_map = {}
        cls._field_ids = []
        for index, field in enumerate(cls._fields):
            if len(field) < 3:
                field = field + ({},)
                cls._fields[index] = field
            cls._field_map[field[0]] = index
            cls._field_ids.append(_build_id_tuple(field[2], field[1]))

        if cls._oid_pair is not None:
            cls._oid_nums = (cls._field_map[cls._oid_pair[0]], cls._field_map[cls._oid_pair[1]])

    def _determine_spec(self, index):
        """
        Determine how a value for a field should be constructed

        :param index:
            The field number

        :return:
            A tuple containing the following elements:
             - unicode string of the field name
             - Ans1Value class of the field spec
             - Asn1Value class of the value spec
             - None or dict of params to pass to the field spec
             - None or Asn1Value class indicating the value spec was derived fomr an OID or a spec callback
        """

        name, field_spec, field_params = self._fields[index]
        value_spec = field_spec
        spec_override = None

        if self._spec_callbacks is not None and name in self._spec_callbacks:
            callback = self._spec_callbacks[name]
            spec_override = callback(self)
            if spec_override:
                # Allow a spec callback to specify both the base spec and
                # the override, for situations such as OctetString and parse_as
                if isinstance(spec_override, tuple) and len(spec_override) == 2:
                    field_spec, value_spec = spec_override
                    if value_spec is None:
                        value_spec = field_spec
                        spec_override = None
                else:
                    value_spec = spec_override

        elif self._oid_nums is not None and self._oid_nums[1] == index:
            oid = self._lazy_child(self._oid_nums[0]).native
            if oid in self._oid_specs:
                spec_override = self._oid_specs[oid]
                value_spec = spec_override

        return (name, field_spec, value_spec, field_params, spec_override)

    def _make_value(self, field_name, field_spec, value_spec, field_params, value):
        """
        Contructs an appropriate Asn1Value object for a field

        :param field_name:
            A unicode string of the field name

        :param field_spec:
            An Asn1Value class that is the field spec

        :param value_spec:
            An Asn1Value class that is the vaue spec

        :param field_params:
            None or a dict of params for the field spec

        :param value:
            The value to construct an Asn1Value object from

        :return:
            An instance of a child class of Asn1Value
        """

        if value is None and 'optional' in field_params:
            return VOID

        specs_different = field_spec != value_spec
        is_any = issubclass(field_spec, Any)

        if issubclass(value_spec, Choice):
            if not isinstance(value, Asn1Value):
                raise ValueError(unwrap(
                    '''
                    Can not set a native python value to %s, which has the
                    choice type of %s – value must be an instance of Asn1Value
                    ''',
                    field_name,
                    type_name(value_spec)
                ))
            if not isinstance(value, value_spec):
                wrapper = value_spec()
                wrapper.validate(value.class_, value.tag, value.contents)
                wrapper._parsed = value
                new_value = wrapper
            else:
                new_value = value

        elif isinstance(value, field_spec):
            new_value = value
            if specs_different:
                new_value.parse(value_spec)

        elif (not specs_different or is_any) and not isinstance(value, value_spec):
            new_value = value_spec(value, **field_params)

        else:
            if isinstance(value, value_spec):
                new_value = value
            else:
                new_value = value_spec(value)

            # For when the field is OctetString or OctetBitString with embedded
            # values we need to wrap the value in the field spec to get the
            # appropriate encoded value.
            if specs_different and not is_any:
                wrapper = field_spec(value=new_value.dump(), **field_params)
                wrapper._parsed = (new_value, new_value.__class__, None)
                new_value = wrapper

        new_value = _fix_tagging(new_value, field_params)

        return new_value

    def _parse_children(self, recurse=False):
        """
        Parses the contents and generates Asn1Value objects based on the
        definitions from _fields.

        :param recurse:
            If child objects that are Sequence or SequenceOf objects should
            be recursively parsed

        :raises:
            ValueError - when an error occurs parsing child objects
        """

        if self._contents is None:
            if self._fields:
                self.children = [VOID] * len(self._fields)
                for index, (_, _, params) in enumerate(self._fields):
                    if 'default' in params:
                        field_name, field_spec, value_spec, field_params, _ = self._determine_spec(index)
                        self.children[index] = self._make_value(field_name, field_spec, value_spec, field_params, None)
            return

        try:
            self.children = []
            contents_length = len(self._contents)
            child_pointer = 0
            field = 0
            seen_field = 1
            field_len = len(self._fields)
            while child_pointer < contents_length:
                parts, num_bytes = _parse(self._contents, pointer=child_pointer)

                if field < field_len:
                    _, field_spec, value_spec, field_params, spec_override = self._determine_spec(field)

                    # If the next value is optional or default, allow it to be absent
                    if 'optional' in field_params or 'default' in field_params:
                        id_ = (parts[0], parts[2])

                        no_id_match = self._field_ids[field] != id_
                        not_any = field_spec != Any
                        if no_id_match and not_any:

                            # See if the value is a valid choice before assuming
                            # that we have a missing optional or default value
                            choice_match = False
                            if issubclass(field_spec, Choice):
                                try:
                                    tester = field_spec(**field_params)
                                    tester.validate(id_[0], id_[1], parts[4])
                                    choice_match = True
                                except (ValueError):
                                    pass

                            if not choice_match:
                                if 'optional' in field_params:
                                    self.children.append(VOID)
                                else:
                                    self.children.append(field_spec(**field_params))
                                field += 1
                                continue

                    if field_spec is None or (spec_override and issubclass(field_spec, Any)):
                        field_spec = value_spec
                        spec_override = None

                    if spec_override:
                        child = parts + (field_spec, field_params, value_spec)
                    else:
                        child = parts + (field_spec, field_params)

                # Handle situations where an optional or defaulted field definition is incorrect
                elif field_len > 0 and seen_field <= field_len:
                    missed_fields = []
                    prev_field = field - 1
                    while prev_field >= 0:
                        prev_field_info = self._fields[prev_field]
                        if len(prev_field_info) < 3:
                            break
                        if 'optional' in prev_field_info[2] or 'default' in prev_field_info[2]:
                            missed_fields.append(prev_field_info[0])
                        prev_field -= 1
                    plural = 's' if len(missed_fields) > 1 else ''
                    missed_field_names = ', '.join(missed_fields)
                    raise ValueError(unwrap(
                        '''
                        Data for field %s (%s class, %s method, tag %s) does
                        not match the field definition%s of %s
                        ''',
                        seen_field,
                        CLASS_NUM_TO_NAME_MAP.get(parts[0]),
                        METHOD_NUM_TO_NAME_MAP.get(parts[1]),
                        parts[2],
                        plural,
                        missed_field_names
                    ))

                else:
                    child = parts

                if recurse:
                    child = _build(*child)
                    if isinstance(child, (Sequence, SequenceOf)):
                        child._parse_children(recurse=True)

                self.children.append(child)
                child_pointer += num_bytes
                field += 1
                seen_field += 1

            index = len(self.children)
            while index < field_len:
                name, field_spec, field_params = self._fields[index]
                if 'default' in field_params:
                    self.children.append(field_spec(**field_params))
                elif 'optional' in field_params:
                    self.children.append(VOID)
                else:
                    raise ValueError(unwrap(
                        '''
                        Field "%s" is missing from structure
                        ''',
                        name
                    ))
                index += 1

        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while parsing %s' % type_name(self),) + args
            raise e

    def spec(self, field_name):
        """
        Determines the spec to use for the field specified. Depending on how
        the spec is determined (_oid_pair or _spec_callbacks), it may be
        necessary to set preceeding field values before calling this. Usually
        specs, if dynamic, are controlled by a preceeding ObjectIdentifier
        field.

        :param field_name:
            A unicode string of the field name to get the spec for

        :return:
            A child class of asn1crypto.core.Asn1Value that the field must be
            encoded using
        """

        if not isinstance(field_name, str_cls):
            raise TypeError(unwrap(
                '''
                field_name must be a unicode string, not %s
                ''',
                type_name(field_name)
            ))

        if self._fields is None:
            raise ValueError(unwrap(
                '''
                Unable to retrieve spec for field %s in the class %s because
                _fields has not been set
                ''',
                repr(field_name),
                type_name(self)
            ))

        index = self._field_map[field_name]
        info = self._determine_spec(index)

        return info[2]

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            An OrderedDict or None. If an OrderedDict, all child values are
            recursively converted to native representation also.
        """

        if self.contents is None:
            return None

        if self._native is None:
            if self.children is None:
                self._parse_children(recurse=True)
            self._native = OrderedDict()
            for index, child in enumerate(self.children):
                if isinstance(child, tuple):
                    child = _build(*child)
                    self.children[index] = child
                try:
                    name = self._fields[index][0]
                except (IndexError):
                    name = str_cls(index)
                self._native[name] = child.native
        return self._native

    def _copy(self, other, copy_func):
        """
        Copies the contents of another Asn1Value object to itself

        :param object:
            Another instance of the same class

        :param copy_func:
            An reference of copy.copy() or copy.deepcopy() to use when copying
            lists, dicts and objects
        """

        if self.__class__ != other.__class__:
            raise TypeError(unwrap(
                '''
                Can not copy values from %s object to %s object
                ''',
                type_name(other),
                type_name(self)
            ))

        self.contents = other.contents
        self._native = copy_func(other._native)
        if self.children is not None:
            self.children = []
            for child in other.children:
                if isinstance(child, tuple):
                    self.children.append(child)
                else:
                    self.children.append(child.copy())

    def debug(self, nest_level=1):
        """
        Show the binary data and parsed data in a tree structure
        """

        if self.children is None:
            self._parse_children()

        prefix = '  ' * nest_level
        _basic_debug(prefix, self)
        for field_name in self:
            child = self._lazy_child(self._field_map[field_name])
            if child is not VOID:
                print('%s    Field "%s"' % (prefix, field_name))
                child.debug(nest_level + 3)

    def dump(self, force=False):
        """
        Encodes the value using DER

        :param force:
            If the encoded contents already exist, clear them and regenerate
            to ensure they are in DER format instead of BER format

        :return:
            A byte string of the DER-encoded value
        """

        if force:
            self._set_contents(force=force)

        return Asn1Value.dump(self)


class SequenceOf(Asn1Value):
    """
    Represents a sequence (ordered) of a single type of values from ASN.1 as a
    Python object with a list-like interface
    """

    tag = 16

    class_ = 0
    method = 1

    # A list of child objects
    children = None

    # SequenceOf overrides .contents to be a property so that the mutated state
    # of child objects can be checked to ensure everything is up-to-date
    _contents = None

    # Variable to track if the object has been mutated
    _mutated = False

    # An Asn1Value class to use when parsing children
    _child_spec = None

    def __init__(self, value=None, default=None, contents=None, spec=None, **kwargs):
        """
        Allows setting child objects and the _child_spec via the spec parameter
        before passing everything else along to Asn1Value.__init__()

        :param value:
            A native Python datatype to initialize the object value with

        :param default:
            The default value if no value is specified

        :param contents:
            A byte string of the encoded contents of the value

        :param spec:
            A class derived from Asn1Value to use to parse children
        """

        if spec:
            self._child_spec = spec

        Asn1Value.__init__(self, **kwargs)

        try:
            if contents is not None:
                self.contents = contents
            else:
                if value is None and default is not None:
                    value = default

                if value is not None:
                    for index, child in enumerate(value):
                        self.__setitem__(index, child)

                    # Make sure a blank list is serialized
                    if self.contents is None:
                        self._set_contents()

        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while constructing %s' % type_name(self),) + args
            raise e

    @property
    def contents(self):
        """
        :return:
            A byte string of the DER-encoded contents of the sequence
        """

        if self.children is None:
            return self._contents

        if self._is_mutated():
            self._set_contents()

        return self._contents

    @contents.setter
    def contents(self, value):
        """
        :param value:
            A byte string of the DER-encoded contents of the sequence
        """

        self._contents = value

    def _is_mutated(self):
        """
        :return:
            A boolean - if the sequence or any children (recursively) have been
            mutated
        """

        mutated = self._mutated
        if self.children is not None:
            for child in self.children:
                if isinstance(child, Sequence) or isinstance(child, SequenceOf):
                    mutated = mutated or child._is_mutated()

        return mutated

    def _lazy_child(self, index):
        """
        Builds a child object if the child has only been parsed into a tuple so far
        """

        child = self.children[index]
        if isinstance(child, tuple):
            child = _build(*child)
            self.children[index] = child
        return child

    def _make_value(self, value):
        """
        Constructs a _child_spec value from a native Python data type, or
        an appropriate Asn1Value object

        :param value:
            A native Python value, or some child of Asn1Value

        :return:
            An object of type _child_spec
        """

        if isinstance(value, self._child_spec):
            new_value = value

        elif issubclass(self._child_spec, Any):
            if isinstance(value, Asn1Value):
                new_value = value
            else:
                raise ValueError(unwrap(
                    '''
                    Can not set a native python value to %s where the
                    _child_spec is Any – value must be an instance of Asn1Value
                    ''',
                    type_name(self)
                ))

        elif issubclass(self._child_spec, Choice):
            if not isinstance(value, Asn1Value):
                raise ValueError(unwrap(
                    '''
                    Can not set a native python value to %s where the
                    _child_spec is the choice type %s – value must be an
                    instance of Asn1Value
                    ''',
                    type_name(self),
                    self._child_spec.__name__
                ))
            if not isinstance(value, self._child_spec):
                wrapper = self._child_spec()
                wrapper.validate(value.class_, value.tag, value.contents)
                wrapper._parsed = value
                value = wrapper
            new_value = value

        else:
            return self._child_spec(value=value)

        params = {}
        if self._child_spec.tag_type is not None:
            params['tag_type'] = self._child_spec.tag_type
            if params['tag_type'] == 'explicit':
                params['tag'] = self._child_spec.explicit_tag
            else:
                params['tag'] = self._child_spec.tag

        return _fix_tagging(new_value, params)

    def __len__(self):
        """
        :return:
            An integer
        """
        # We inline this checks to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        return len(self.children)

    def __getitem__(self, key):
        """
        Allows accessing children via index

        :param key:
            Integer index of child
        """

        # We inline this checks to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        return self._lazy_child(key)

    def __setitem__(self, key, value):
        """
        Allows overriding a child via index

        :param key:
            Integer index of child

        :param value:
            Native python datatype that will be passed to _child_spec to create
            new child object
        """

        # We inline this checks to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        new_value = self._make_value(value)

        # If adding at the end, create a space for the new value
        if key == len(self.children):
            self.children.append(None)
            if self._native is not None:
                self._native.append(None)

        self.children[key] = new_value

        if self._native is not None:
            self._native[key] = self.children[key].native

        self._mutated = True

    def __delitem__(self, key):
        """
        Allows removing a child via index

        :param key:
            Integer index of child
        """

        # We inline this checks to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        self.children.pop(key)
        if self._native is not None:
            self._native.pop(key)

        self._mutated = True

    def __iter__(self):
        """
        :return:
            An iter() of child objects
        """

        # We inline this checks to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        for index in range(0, len(self.children)):
            yield self._lazy_child(index)

    def __contains__(self, item):
        """
        :param item:
            An object of the type cls._child_spec

        :return:
            A boolean if the item is contained in this SequenceOf
        """

        if item is None or item is VOID:
            return False

        if not isinstance(item, self._child_spec):
            raise TypeError(unwrap(
                '''
                Checking membership in %s is only available for instances of
                %s, not %s
                ''',
                type_name(self),
                type_name(self._child_spec),
                type_name(item)
            ))

        for child in self:
            if child == item:
                return True

        return False

    def append(self, value):
        """
        Allows adding a child to the end of the sequence

        :param value:
            Native python datatype that will be passed to _child_spec to create
            new child object
        """

        # We inline this checks to prevent method invocation each time
        if self.children is None:
            self._parse_children()

        self.children.append(self._make_value(value))

        if self._native is not None:
            self._native.append(self.children[-1].native)

        self._mutated = True

    def _set_contents(self, force=False):
        """
        Encodes all child objects into the contents for this object

        :param force:
            Ensure all contents are in DER format instead of possibly using
            cached BER-encoded data
        """

        if self.children is None:
            self._parse_children()

        contents = BytesIO()
        for child in self:
            contents.write(child.dump(force=force))
        self._contents = contents.getvalue()
        self._header = None
        if self._trailer != b'':
            self._trailer = b''

    def _parse_children(self, recurse=False):
        """
        Parses the contents and generates Asn1Value objects based on the
        definitions from _child_spec.

        :param recurse:
            If child objects that are Sequence or SequenceOf objects should
            be recursively parsed

        :raises:
            ValueError - when an error occurs parsing child objects
        """

        try:
            self.children = []
            if self._contents is None:
                return
            contents_length = len(self._contents)
            child_pointer = 0
            while child_pointer < contents_length:
                parts, num_bytes = _parse(self._contents, pointer=child_pointer)
                if self._child_spec:
                    child = parts + (self._child_spec,)
                else:
                    child = parts
                if recurse:
                    child = _build(*child)
                    if isinstance(child, (Sequence, SequenceOf)):
                        child._parse_children(recurse=True)
                self.children.append(child)
                child_pointer += num_bytes
        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while parsing %s' % type_name(self),) + args
            raise e

    def spec(self):
        """
        Determines the spec to use for child values.

        :return:
            A child class of asn1crypto.core.Asn1Value that child values must be
            encoded using
        """

        return self._child_spec

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            A list or None. If a list, all child values are recursively
            converted to native representation also.
        """

        if self.contents is None:
            return None

        if self._native is None:
            if self.children is None:
                self._parse_children(recurse=True)
            self._native = [child.native for child in self]
        return self._native

    def _copy(self, other, copy_func):
        """
        Copies the contents of another Asn1Value object to itself

        :param object:
            Another instance of the same class

        :param copy_func:
            An reference of copy.copy() or copy.deepcopy() to use when copying
            lists, dicts and objects
        """

        if self.__class__ != other.__class__:
            raise TypeError(unwrap(
                '''
                Can not copy values from %s object to %s object
                ''',
                type_name(other),
                type_name(self)
            ))

        self.contents = other.contents
        self._native = copy_func(other._native)
        if self.children is not None:
            self.children = []
            for child in other.children:
                if isinstance(child, tuple):
                    self.children.append(child)
                else:
                    self.children.append(child.copy())

    def debug(self, nest_level=1):
        """
        Show the binary data and parsed data in a tree structure
        """

        if self.children is None:
            self._parse_children()

        prefix = '  ' * nest_level
        _basic_debug(prefix, self)
        for child in self:
            child.debug(nest_level + 1)

    def dump(self, force=False):
        """
        Encodes the value using DER

        :param force:
            If the encoded contents already exist, clear them and regenerate
            to ensure they are in DER format instead of BER format

        :return:
            A byte string of the DER-encoded value
        """

        if force:
            self._set_contents(force=force)

        return Asn1Value.dump(self)


class Set(Sequence):
    """
    Represents a set of fields (unordered) from ASN.1 as a Python object with a
    dict-like interface
    """

    method = 1
    class_ = 0
    tag = 17

    # A dict of 2-element tuples in the form (class_, tag) as keys and integers
    # as values that are the index of the field in _fields
    _field_ids = None

    def _setup(self):
        """
        Generates _field_map, _field_ids and _oid_nums for use in parsing
        """

        cls = self.__class__
        cls._field_map = {}
        cls._field_ids = {}
        for index, field in enumerate(cls._fields):
            if len(field) < 3:
                field = field + ({},)
                cls._fields[index] = field
            cls._field_map[field[0]] = index
            cls._field_ids[_build_id_tuple(field[2], field[1])] = index

        if cls._oid_pair is not None:
            cls._oid_nums = (cls._field_map[cls._oid_pair[0]], cls._field_map[cls._oid_pair[1]])

    def _parse_children(self, recurse=False):
        """
        Parses the contents and generates Asn1Value objects based on the
        definitions from _fields.

        :param recurse:
            If child objects that are Sequence or SequenceOf objects should
            be recursively parsed

        :raises:
            ValueError - when an error occurs parsing child objects
        """

        try:
            child_map = {}
            contents_length = len(self.contents)
            child_pointer = 0
            while child_pointer < contents_length:
                parts, num_bytes = _parse(self.contents, pointer=child_pointer)

                id_ = (parts[0], parts[2])

                field = self._field_ids[id_]
                _, spec, field_params = self._fields[field]
                parse_as = None

                if self._oid_nums is not None and self._oid_nums[1] == field:
                    oid = self.children[self._oid_nums[0]].native
                    if isinstance(spec, Any):
                        spec = self._oid_specs[oid]
                    else:
                        parse_as = self._oid_specs[oid]

                if parse_as:
                    child = parts + (spec, field_params, parse_as)
                else:
                    child = parts + (spec, field_params)

                if recurse:
                    child = _build(*child)
                    if isinstance(child, (Sequence, SequenceOf)):
                        child._parse_children(recurse=True)

                child_map[field] = child
                child_pointer += num_bytes

            total_fields = len(self._fields)

            for index in range(0, total_fields):
                if index in child_map:
                    continue
                name, spec, field_params = self._fields[index]

                missing = False

                if not field_params:
                    missing = True
                elif 'optional' not in field_params and 'default' not in field_params:
                    missing = True
                elif 'optional' in field_params:
                    child_map[index] = VOID
                elif 'default' in field_params:
                    child_map[index] = spec(**field_params)

                if missing:
                    raise ValueError(unwrap(
                        '''
                        Missing required field "%s" from %s
                        ''',
                        name,
                        type_name(self)
                    ))

            self.children = []
            for index in range(0, total_fields):
                self.children.append(child_map[index])

        except (ValueError, TypeError) as e:
            args = e.args[1:]
            e.args = (e.args[0] + '\n    while parsing %s' % type_name(self),) + args
            raise e


class SetOf(SequenceOf):
    """
    Represents a set (unordered) of a single type of values from ASN.1 as a
    Python object with a list-like interface
    """

    tag = 17


class EmbeddedPdv(Sequence):
    """
    A sequence structure
    """

    tag = 11


class NumericString(AbstractString):
    """
    Represents a numeric string from ASN.1 as a Python unicode string
    """

    tag = 18
    _encoding = 'latin1'


class PrintableString(AbstractString):
    """
    Represents a printable string from ASN.1 as a Python unicode string
    """

    tag = 19
    _encoding = 'latin1'


class TeletexString(AbstractString):
    """
    Represents a teletex string from ASN.1 as a Python unicode string
    """

    tag = 20
    _encoding = 'teletex'


class VideotexString(OctetString):
    """
    Represents a videotex string from ASN.1 as a Python byte string
    """

    tag = 21


class IA5String(AbstractString):
    """
    Represents an IA5 string from ASN.1 as a Python unicode string
    """

    tag = 22
    _encoding = 'ascii'


class AbstractTime(AbstractString):
    """
    Represents a time from ASN.1 as a Python datetime.datetime object
    """

    @property
    def native(self):
        """
        The a native Python datatype representation of this value

        :return:
            A datetime.datetime object in the UTC timezone or None
        """

        if self.contents is None:
            return None

        if self._native is None:
            string = str_cls(self)
            has_timezone = re.search('[-\\+]', string)

            # We don't know what timezone it is in, or it is UTC because of a Z
            # suffix, so we just assume UTC
            if not has_timezone:
                string = string.rstrip('Z')
                date = self._date_by_len(string)
                self._native = date.replace(tzinfo=timezone.utc)

            else:
                # Python 2 doesn't support the %z format code, so we have to manually
                # process the timezone offset.
                date = self._date_by_len(string[0:-5])

                hours = int(string[-4:-2])
                minutes = int(string[-2:])
                delta = timedelta(hours=abs(hours), minutes=minutes)
                if hours < 0:
                    date -= delta
                else:
                    date += delta

                self._native = date.replace(tzinfo=timezone.utc)

        return self._native


class UTCTime(AbstractTime):
    """
    Represents a UTC time from ASN.1 as a Python datetime.datetime object in UTC
    """

    tag = 23

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            A unicode string or a datetime.datetime object

        :raises:
            ValueError - when an invalid value is passed
        """

        if isinstance(value, datetime):
            value = value.strftime('%y%m%d%H%M%SZ')
            if py2:
                value = value.decode('ascii')

        AbstractString.set(self, value)
        # Set it to None and let the class take care of converting the next
        # time that .native is called
        self._native = None

    def _date_by_len(self, string):
        """
        Parses a date from a string based on its length

        :param string:
            A unicode string to parse

        :return:
            A datetime.datetime object or a unicode string
        """

        strlen = len(string)

        year_num = int(string[0:2])
        if year_num < 50:
            prefix = '20'
        else:
            prefix = '19'

        if strlen == 10:
            return datetime.strptime(prefix + string, '%Y%m%d%H%M')

        if strlen == 12:
            return datetime.strptime(prefix + string, '%Y%m%d%H%M%S')

        return string


class GeneralizedTime(AbstractTime):
    """
    Represents a generalized time from ASN.1 as a Python datetime.datetime
    object in UTC
    """

    tag = 24

    def set(self, value):
        """
        Sets the value of the object

        :param value:
            A unicode string or a datetime.datetime object

        :raises:
            ValueError - when an invalid value is passed
        """

        if isinstance(value, datetime):
            value = value.strftime('%Y%m%d%H%M%SZ')
            if py2:
                value = value.decode('ascii')

        AbstractString.set(self, value)
        # Set it to None and let the class take care of converting the next
        # time that .native is called
        self._native = None

    def _date_by_len(self, string):
        """
        Parses a date from a string based on its length

        :param string:
            A unicode string to parse

        :return:
            A datetime.datetime object or a unicode string
        """

        strlen = len(string)

        if strlen == 10:
            return datetime.strptime(string, '%Y%m%d%H')

        if strlen == 12:
            return datetime.strptime(string, '%Y%m%d%H%M')

        if strlen == 14:
            return datetime.strptime(string, '%Y%m%d%H%M%S')

        if strlen == 18:
            return datetime.strptime(string, '%Y%m%d%H%M%S.%f')

        return string


class GraphicString(AbstractString):
    """
    Represents a graphic string from ASN.1 as a Python unicode string
    """

    tag = 25
    # This is technically not correct since this type can contain any charset
    _encoding = 'latin1'


class VisibleString(AbstractString):
    """
    Represents a visible string from ASN.1 as a Python unicode string
    """

    tag = 26
    _encoding = 'latin1'


class GeneralString(AbstractString):
    """
    Represents a general string from ASN.1 as a Python unicode string
    """

    tag = 27
    # This is technically not correct since this type can contain any charset
    _encoding = 'latin1'


class UniversalString(AbstractString):
    """
    Represents a universal string from ASN.1 as a Python unicode string
    """

    tag = 28
    _encoding = 'utf-32-be'


class CharacterString(AbstractString):
    """
    Represents a character string from ASN.1 as a Python unicode string
    """

    tag = 29
    # This is technically not correct since this type can contain any charset
    _encoding = 'latin1'


class BMPString(AbstractString):
    """
    Represents a BMP string from ASN.1 as a Python unicode string
    """

    tag = 30
    _encoding = 'utf-16-be'


def _basic_debug(prefix, self):
    """
    Prints out basic information about an Asn1Value object. Extracted for reuse
    among different classes that customize the debug information.

    :param prefix:
        A unicode string of spaces to prefix output line with

    :param self:
        The object to print the debugging information about
    """

    print('%s%s Object #%s' % (prefix, type_name(self), id(self)))
    if self._header:
        print('%s  Header: 0x%s' % (prefix, binascii.hexlify(self._header or b'').decode('utf-8')))

    has_header = self.method is not None and self.class_ is not None and self.tag is not None
    if has_header:
        method_name = METHOD_NUM_TO_NAME_MAP.get(self.method)
        class_name = CLASS_NUM_TO_NAME_MAP.get(self.class_)

    if self.tag_type == 'explicit':
        print(
            '%s    %s tag %s (explicitly tagged)' %
            (
                prefix,
                CLASS_NUM_TO_NAME_MAP.get(self.explicit_class),
                self.explicit_tag
            )
        )
        if has_header:
            print('%s      %s %s %s' % (prefix, method_name, class_name, self.tag))

    elif self.tag_type == 'implicit':
        if has_header:
            print('%s    %s %s tag %s (implicitly tagged)' % (prefix, method_name, class_name, self.tag))

    elif has_header:
        print('%s    %s %s tag %s' % (prefix, method_name, class_name, self.tag))

    print('%s  Data: 0x%s' % (prefix, binascii.hexlify(self.contents or b'').decode('utf-8')))


def _fix_tagging(value, params):
    """
    Checks if a value is properly tagged based on the spec, and re/untags as
    necessary

    :param value:
        An Asn1Value object

    :param params:
        A dict of spec params

    :return:
        An Asn1Value that is properly tagged
    """

    if 'tag_type' in params:
        required_tag_type = params['tag_type']
        retag = False

        if required_tag_type != value.tag_type:
            retag = True

        elif required_tag_type == 'explicit' and value.explicit_tag != params['tag']:
            retag = True

        elif required_tag_type == 'implicit' and value.tag != params['tag']:
            retag = True

        if retag:
            return value.retag(params['tag_type'], params['tag'])
        return value

    if value.tag_type:
        return value.untag()

    return value


def _dump_header(class_, method, tag, contents):
    header = b''

    id_num = 0
    id_num |= class_ << 6
    id_num |= method << 5

    tag = tag

    if tag >= 31:
        header += chr_cls(id_num | 31)
        while tag > 0:
            continuation_bit = 0x80 if tag > 0x7F else 0
            header += chr_cls(continuation_bit | (tag & 0x7F))
            tag = tag >> 7
    else:
        header += chr_cls(id_num | tag)

    length = len(contents)
    if length <= 127:
        header += chr_cls(length)
    else:
        length_bytes = int_to_bytes(length)
        header += chr_cls(0x80 | len(length_bytes))
        header += length_bytes

    return header


def _build_id_tuple(params, spec):
    """
    Builds a 2-element tuple used to identify fields by grabbing the class_
    and tag from an Asn1Value class and the params dict being passed to it

    :param params:
        A dict of params to pass to spec

    :param spec:
        An Asn1Value class

    :return:
        A 2-element integer tuple in the form (class_, tag)
    """

    # Handle situations where the the spec is not known at setup time
    if spec is None:
        return (None, None)

    required_class = spec.class_
    required_tag = spec.tag

    tag_type = params.get('tag_type', spec.tag_type)
    if tag_type is not None:
        required_class = 2

    required_class = params.get('class_', required_class)
    required_tag = params.get('tag', required_tag)

    return (required_class, required_tag)


def _build(class_, method, tag, header, contents, trailer, spec=None, spec_params=None, nested_spec=None):
    """
    Builds an Asn1Value object generically, or using a spec with optional params

    :param class_:
        An integer representing the ASN.1 class

    :param method:
        An integer representing the ASN.1 method

    :param tag:
        An integer representing the ASN.1 tag

    :param header:
        A byte string of the ASN.1 header (class, method, tag, length)

    :param contents:
        A byte string of the ASN.1 value

    :param trailer:
        A byte string of any ASN.1 trailer (only used by indefinite length encodings)

    :param spec:
        A class derived from Asn1Value that defines what class_ and tag the
        value should have, and the semantics of the encoded value. The
        return value will be of this type. If omitted, the encoded value
        will be decoded using the standard universal tag based on the
        encoded tag number.

    :param spec_params:
        A dict of params to pass to the spec object

    :param nested_spec:
        For certain Asn1Value classes (such as OctetString and BitString), the
        contents can be further parsed and interpreted as another Asn1Value.
        This parameter controls the spec for that sub-parsing.

    :return:
        An object of the type spec, or if not specified, a child of Asn1Value
    """

    if header is None:
        return VOID

    # If an explicit specification was passed in, make sure it matches
    if spec is not None:
        if spec_params:
            value = spec(contents=contents, **spec_params)
        else:
            value = spec(contents=contents)

        is_choice = isinstance(value, Choice)

        if spec == Any:
            pass

        elif value.tag_type == 'explicit':
            if class_ != value.explicit_class:
                raise ValueError(unwrap(
                    '''
                    Error parsing %s - explicitly-tagged class should have been
                    %s, but %s was found
                    ''',
                    type_name(value),
                    CLASS_NUM_TO_NAME_MAP.get(value.explicit_class),
                    CLASS_NUM_TO_NAME_MAP.get(class_, class_)
                ))
            if method != 1:
                raise ValueError(unwrap(
                    '''
                    Error parsing %s - explicitly-tagged method should have
                    been %s, but %s was found
                    ''',
                    type_name(value),
                    METHOD_NUM_TO_NAME_MAP.get(1),
                    METHOD_NUM_TO_NAME_MAP.get(method, method)
                ))
            if tag != value.explicit_tag:
                raise ValueError(unwrap(
                    '''
                    Error parsing %s - explicitly-tagged tag should have been
                    %s, but %s was found
                    ''',
                    type_name(value),
                    value.explicit_tag,
                    tag
                ))

        elif is_choice:
            value.validate(class_, tag, contents)

        else:
            if class_ != value.class_:
                raise ValueError(unwrap(
                    '''
                    Error parsing %s - class should have been %s, but %s was
                    found
                    ''',
                    type_name(value),
                    CLASS_NUM_TO_NAME_MAP.get(value.class_),
                    CLASS_NUM_TO_NAME_MAP.get(class_, class_)
                ))
            if method != value.method:
                raise ValueError(unwrap(
                    '''
                    Error parsing %s - method should have been %s, but %s was found
                    ''',
                    type_name(value),
                    METHOD_NUM_TO_NAME_MAP.get(value.method),
                    METHOD_NUM_TO_NAME_MAP.get(method, method)
                ))
            if tag != value.tag:
                raise ValueError(unwrap(
                    '''
                    Error parsing %s - tag should have been %s, but %s was found
                    ''',
                    type_name(value),
                    value.tag,
                    tag
                ))

    # For explicitly tagged, un-speced parsings, we use a generic container
    # since we will be parsing the contents and discarding the outer object
    # anyway a little further on
    elif spec_params and 'tag_type' in spec_params and spec_params['tag_type'] == 'explicit':
        value = Asn1Value(contents=contents, **spec_params)
        is_choice = False

    # If no spec was specified, allow anything and just process what
    # is in the input data
    else:
        universal_specs = {
            1: Boolean,
            2: Integer,
            3: BitString,
            4: OctetString,
            5: Null,
            6: ObjectIdentifier,
            7: ObjectDescriptor,
            8: InstanceOf,
            9: Real,
            10: Enumerated,
            11: EmbeddedPdv,
            12: UTF8String,
            13: RelativeOid,
            16: Sequence,
            17: Set,
            18: NumericString,
            19: PrintableString,
            20: TeletexString,
            21: VideotexString,
            22: IA5String,
            23: UTCTime,
            24: GeneralizedTime,
            25: GraphicString,
            26: VisibleString,
            27: GeneralString,
            28: UniversalString,
            29: CharacterString,
            30: BMPString
        }
        if tag not in universal_specs:
            raise ValueError(unwrap(
                '''
                Unknown element - %s class, %s method, tag %s
                ''',
                CLASS_NUM_TO_NAME_MAP.get(class_),
                METHOD_NUM_TO_NAME_MAP.get(method),
                tag
            ))

        spec = universal_specs[tag]

        value = spec(contents=contents, class_=class_)
        is_choice = False

    value._header = header
    if trailer is not None and trailer != b'':
        value._trailer = trailer

    # Destroy any default value that our contents have overwritten
    value._native = None

    # For explicitly tagged values, parse the inner value and pull it out
    if value.tag_type == 'explicit':
        original_value = value
        (class_, method, tag, header, contents, trailer), _ = _parse(value.contents)
        value = _build(class_, method, tag, header, contents, trailer, spec=spec)
        value._header = original_value._header + header
        value._trailer += original_value._trailer
        value.tag_type = 'explicit'
        value.explicit_class = original_value.explicit_class
        value.explicit_tag = original_value.explicit_tag
    elif is_choice:
        value.contents = value._header + value.contents
        value._header = b''

    try:
        # Force parsing the Choice now
        if is_choice:
            value.parse()

        if nested_spec:
            value.parse(nested_spec)
    except (ValueError, TypeError) as e:
        args = e.args[1:]
        e.args = (e.args[0] + '\n    while parsing %s' % type_name(value),) + args
        raise e

    return value


def _parse(encoded_data, pointer=0):
    """
    Parses a byte string into component parts

    :param encoded_data:
        A byte string that contains BER-encoded data

    :param pointer:
        The index in the byte string to parse from

    :return:
        A 2-element tuple:
         - 0: A tuple of (class_, method, tag, header, content, trailer)
         - 1: An integer indicating how many bytes were consumed
    """

    if len(encoded_data) == 0:
        return ((None, None, None, None, None, None), 0)

    encoded_length = len(encoded_data)

    start = pointer

    first_octet = ord(encoded_data[pointer]) if py2 else encoded_data[pointer]
    pointer += 1

    class_ = first_octet >> 6
    method = (first_octet >> 5) & 1

    tag = first_octet & 31
    # Base 128 length using 8th bit as continuation indicator
    if tag == 31:
        tag = 0
        while True:
            num = ord(encoded_data[pointer]) if py2 else encoded_data[pointer]
            pointer += 1
            tag *= 128
            tag += num & 127
            if num >> 7 == 0:
                break

    if pointer + 1 > encoded_length:
        raise ValueError(unwrap(
            '''
            Insufficient data - %s bytes requested but only %s available
            ''',
            pointer + 1,
            encoded_length
        ))
    length_octet = ord(encoded_data[pointer]) if py2 else encoded_data[pointer]

    pointer += 1
    length_type = length_octet >> 7
    if length_type == 1:
        length = 0
        remaining_length_octets = length_octet & 127
        while remaining_length_octets > 0:
            length *= 256
            if pointer + 1 > encoded_length:
                raise ValueError(unwrap(
                    '''
                    Insufficient data - %s bytes requested but only %s available
                    ''',
                    pointer + 1,
                    encoded_length
                ))
            length += ord(encoded_data[pointer]) if py2 else encoded_data[pointer]
            pointer += 1
            remaining_length_octets -= 1
    else:
        length = length_octet & 127

    if pointer > encoded_length:
        raise ValueError(unwrap(
            '''
            Insufficient data - %s bytes requested but only %s available
            ''',
            pointer,
            encoded_length
        ))
    header = encoded_data[start:pointer]

    # Indefinite length
    if length_type == 1 and length == 0:
        end_token = encoded_data.find(b'\x00\x00', pointer)
        if end_token > encoded_length:
            raise ValueError(unwrap(
                '''
                Insufficient data - %s bytes requested but only %s available
                ''',
                end_token,
                encoded_length
            ))
        contents = encoded_data[pointer:end_token]
        pointer = end_token + 2
        trailer = b'\x00\x00'

    else:
        if pointer + length > encoded_length:
            raise ValueError(unwrap(
                '''
                Insufficient data - %s bytes requested but only %s available
                ''',
                pointer + length,
                encoded_length
            ))
        contents = encoded_data[pointer:pointer + length]
        pointer += length
        trailer = b''

    return ((class_, method, tag, header, contents, trailer), pointer - start)


def _parse_build(encoded_data, pointer=0, spec=None, spec_params=None):
    """
    Parses a byte string generically, or using a spec with optional params

    :param encoded_data:
        A byte string that contains BER-encoded data

    :param pointer:
        The index in the byte string to parse from

    :param spec:
        A class derived from Asn1Value that defines what class_ and tag the
        value should have, and the semantics of the encoded value. The
        return value will be of this type. If omitted, the encoded value
        will be decoded using the standard universal tag based on the
        encoded tag number.

    :param spec_params:
        A dict of params to pass to the spec object

    :return:
        A 2-element tuple:
         - 0: An object of the type spec, or if not specified, a child of Asn1Value
         - 1: An integer indicating how many bytes were consumed
    """

    (class_, method, tag, header, contents, trailer), num_bytes = _parse(encoded_data, pointer)
    value = _build(class_, method, tag, header, contents, trailer, spec=spec, spec_params=spec_params)
    return (value, num_bytes)
