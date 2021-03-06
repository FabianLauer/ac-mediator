from ac_mediator.exceptions import ACFieldTranslateException, ACException, ACFilterParsingException
from services.acservice.constants import *
from services.acservice.utils import parse_filter
import pyparsing


def translates_field(field_name):
    """
    This decorator annotates the decorated function with a '_translates_field_name' property
    with a reference to an Audio Commons metadata field name. The '_translates_field_name' property is
    used when BaseACServiceSearchMixin objects are initialized to build a registry of methods that can "translate"
    a specific Audio Commons field (see BaseACServiceSearchMixin.conf_search()
    :param field_name: Audio Commons metadata field name (see services.mixins.constants.py)
    :return: decorated function
    """
    def wrapper(func):
        func._translates_field_name = field_name
        return func
    return wrapper


def translates_filter_for_field(field_name):
    """
    This decorator annotates the decorated function with a '_translates_filter_for_field_name' property
    with a reference to an Audio Commons metadata field name. The '_translates_filter_for_field_name' property is
    used when ACServiceTextSearchMixin objects are initialized to build a registry of methods that can "translate"
    a filter for a specific Audio Commons field (see ACServiceTextSearchMixin.conf_textsearch()).
    :param field_name: Audio Commons metadata field name (see services.mixins.constants.py)
    :return: decorated function
    """
    def wrapper(func):
        func._translates_filter_for_field_name = field_name
        return func
    return wrapper


class BaseACServiceSearchMixin(object):
    """
    Base class for search-related mixins.
    This class is in charge of providing necessary methods for handling translation of metadata field names
    and values between the 3rd party service and the Audio Commons API and ecosystem. In this way, when
    3rd party service returns a list of results with services particular fields and values, we can translate
    these to a unified Audio Commons format.
    Services that implement any of the search functionalities must at least implement:
        - BaseACServiceSearchMixin.format_search_response(self)
        - BaseACServiceSearchMixin.direct_fields_mapping(self) and/or necessary methods for translating individual
          fields using the 'translates_field' decorator
    """

    SERVICE_ID_FIELDNAME = 'id'
    translate_field_methods_registry = None

    def conf_search(self, *args):
        """
        Search for methods in the class that have been annotated with the property '_translates_field_name'.
        These will be methods decorated with the 'translates_field' decorator. Then register methods
        in self.translate_field_methods_registry so that these can be accessed later.
        """
        self.translate_field_methods_registry = dict()
        for method_name in dir(self):
            method = getattr(self, method_name)
            if hasattr(method, '_translates_field_name'):
                self.translate_field_methods_registry[method._translates_field_name] = method

    @property
    def direct_fields_mapping(self):
        """
        Return a dictionary of Audio Commons field names that can be directly mapped to
        service resource fields. 'directly mapped' means that the value can be passed
        to the response unchanged and only the field name needs (probably) to be changed.
        For example, id service provider returns a result such as {'original_filename': 'audio filename'},
        we just need to change 'original_filename' for 'name' in order to make it compatible
        with Audio Commons format. Therefore, the direct_fields_mapping dictionary would include
        an entry like 'AUDIO_COMMONS_TERM_FOR_FIELD_NAME': 'original_filename'.
        :return: dictionary mapping (keys are Audio Commons field names and values are services' resource field names)
        """
        return {}

    def translate_field(self, ac_field_name, result):
        """
        Given an audio commons field name and a dictionary representing a single result entry form a
        service response, return the corresponding field value compatible with the Audio
        Commons API. To perform this translation first we check if the field is available in
        self.direct_fields_mapping. If that is the case, this function simply returns the corresponding
        value according to the field name mapping specified in self.direct_fields_mapping.
        If field name is not available in self.direct_fields_mapping, then we check if it is available
        in the registry of translate field methods self.translate_field_methods_registry which is built
        when running self.conf_search() (see BaseACServiceSearchMixin.conf_search(self, *args).
        If a method for the ac_field_name exists in self.translate_field_methods_registry we call it and
        return its response.
        If field does not exist in self.direct_fields_mapping or self.translate_field_methods_registry
        we raise an exception to inform that field could not be translated.
        :param ac_field_name: name of the field in the Audio Commons API domain
        :param result: dictionary representing a single result entry form a service response
        :return: value of ac_field_name for the given result
        """
        try:
            if ac_field_name in self.direct_fields_mapping:
                return result[self.direct_fields_mapping[ac_field_name]]  # Do direct mapping
            if ac_field_name in self.translate_field_methods_registry:
                return self.translate_field_methods_registry[ac_field_name](result)  # Invoke translate method
        except Exception as e:  # Use generic catch on purpose so we can properly notify the frontend
            raise ACFieldTranslateException(
                    'Can\'t translate field \'{0}\' ({1}: {2})'.format(ac_field_name, e.__class__.__name__, e))
        raise ACFieldTranslateException('Can\'t translate field \'{0}\' (unexpected field)'.format(ac_field_name))

    @property
    def id_prefix(self):
        return self.name + ACID_SEPARATOR_CHAR

    @translates_field(FIELD_ID)
    def translate_field_id(self, result):
        """
        Default implementation for the translation of ID field. It takes the id of the resource
        coming from the service and appends the service name. The id of the resource is taken using the
        SERVICE_ID_FIELDNAME which defaults to 'id'. If this is not the way in which id is provided by the
        service then either SERVICE_ID_FIELDNAME is assigned a different value or this function
        must be overwritten.
        :param result: dictionary representing a single result entry form a service response
        :return: id to uniquely identify resource within the Audio Commons Ecosystem
        """
        return '{0}{1}'.format(self.id_prefix, result[self.SERVICE_ID_FIELDNAME])

    def get_supported_fields(self):
        """
        Checks which AudioCommons fields can be translated to the third party service fields.
        These are the fields supported in 'direct_fields_mapping' and those added in the
        'translate_field_methods_registry' using the @translates_field decorator.
        :return: list of available AudioCommons field names
        """
        return list(self.direct_fields_mapping.keys()) + list(self.translate_field_methods_registry.keys())

    def translate_single_result(self, result, target_fields, format):
        """
        Take an individual search result from a service response in the form of a dictionary
        and translate its keys and values to an Audio Commons API compatible format.
        This method iterates over a given set of target ac_fields and computes the value
        that each field should have in the Audio Commons API context.
        :param result: dictionary representing a single result entry form a service response
        :param target_fields: list of Audio Commons fields to return
        :param format: format with which the response should be returned. Defaults to JSON.
        :return: dictionary representing the single result with keys and values compatible with Audio Commons API
        """
        translated_result = dict()
        if target_fields is None:
            target_fields = list()  # Avoid non iterable error
        for ac_field_name in target_fields:
            try:
                trans_field_value = self.translate_field(ac_field_name, result)
            except ACFieldTranslateException as e:
                # Uncomment following line if we want to set field to None if can't be translated
                # translated_result[ac_field_name] = None
                self.add_response_warning("Can't return unsupported field {0}".format(ac_field_name))
                continue
            translated_result[ac_field_name] = trans_field_value
        return translated_result

    def format_search_response(self, response, common_search_params, format):
        """
        Take the search request response returned from the service and transform it
        to the unified Audio Commons search response definition.

        :param response: dictionary with json search response
        :param common_search_params: common search parameters passed here in case these are needed somewhere
        :param format: format with which the response should be returned. Defaults to JSON.
        :return: dictionary with search results properly formatted
        """
        results = list()
        for result in self.get_results_list_from_response(response):
            translated_result = \
                self.translate_single_result(result,
                                             target_fields=common_search_params.get('fields', None), format=format)
            results.append(translated_result)
        return {
            NUM_RESULTS_PROP: self.get_num_results_from_response(response),
            RESULTS_LIST: results,
        }

    def process_common_search_params(self, common_search_params):
        """
        This method calls all the functions that process common search parameters (i.e. process_x_query_parameter) and
        aggregates their returned query parameters for the third party service request.
        Raise warnings using the BaseACService.add_response_warning method.
        :param common_search_params: common search query parameters as parsed in the corresponding API view
        :return: query parameters dict
        """
        params = dict()

        # Process 'size' query parameter
        size = common_search_params[QUERY_PARAM_SIZE]
        if size is not None:  # size defaults to 15 so it should never be 'None'
            try:
                params.update(self.process_size_query_parameter(size, common_search_params))
            except NotImplementedError as e:
                self.add_response_warning(str(e))

        # Process 'page' query parameter
        page = common_search_params[QUERY_PARAM_PAGE]
        if page is not None:
            try:
                params.update(self.process_page_query_parameter(page, common_search_params))
            except NotImplementedError as e:
                self.add_response_warning(str(e))

        return params

    # ***********************************************************************
    # The methods below are expected to be overwritten by individual services
    # ***********************************************************************

    def get_results_list_from_response(self, response):
        """
        Given the complete response of a search request to the end service, return the list of results.
        :param response: dictionary with the full json response of the request
        :return: list of dict where each dict is a single result
        """
        raise NotImplementedError("Service must implement method BaseACServiceSearchMixin.get_results_list_from_response")

    def get_num_results_from_response(self, response):
        """
        Given the complete response of a search request to the end service, return the total number of results.
        :param response: dictionary with the full json response of the request
        :return: number of total results (integer)
        """
        raise NotImplementedError("Service must implement method BaseACServiceSearchMixin.get_results_list_from_response")

    def process_size_query_parameter(self, size, common_search_params):
        """
        Process 'size' search query parameter and translate it to corresponding query parameter(s)
        for the third party service. Raise warnings using the BaseACService.add_response_warning method.
        The query parameters are returned as a dictionary where keys and values will be sent as keys and values of
        query parameters in the request to the third party service. Typically the returned query parameters dictionary
        will only contain one key/value pair.
        :param size: number of desired results per page (int)
        :param common_search_params: dictionary with other common search query parameters (might not be needed)
        :return: query parameters dict
        """
        raise NotImplementedError("Parameter '{0}' not supported".format(QUERY_PARAM_SIZE))

    def process_page_query_parameter(self, page, common_search_params):
        """
        Process 'page' search query parameter and translate it to corresponding query parameter(s)
        for the third party service. Raise warnings using the BaseACService.add_response_warning method.
        The query parameters are returned as a dictionary where keys and values will be sent as keys and values of
        query parameters in the request to the third party service. Typically the returned query parameters dictionary
        will only contain one key/value pair.
        :param page: requested page number (int)
        :param common_search_params: dictionary with other common search query parameters (might not be needed)
        :return: query parameters dict
        """
        raise NotImplementedError("Parameter '{0}' not supported".format(QUERY_PARAM_PAGE))

    def add_extra_search_query_params(self):
        """
        Return a dictionary with any extra query parameters in key/value pairs that should be added to the
        search request.
        :return: query parameters dict
        """
        return dict()


class ACServiceTextSearchMixin(BaseACServiceSearchMixin):
    """
    Mixin that defines methods to allow text search.
    Services are expected to override methods to adapt them to their own APIs.
    """

    TEXT_SEARCH_ENDPOINT_URL = 'http://example.com/api/search/'

    translate_filter_methods_registry = None

    def conf_textsearch(self, *args):
        """
        Add SEARCH_TEXT_COMPONENT to the list of implemented components.
        Also search for methods in the class that have been annotated with the property
        '_translates_filter_for_field_name'. These will be methods decorated with the 'translates_filter_for_field'
        decorator. Then register methods in self.translate_filter_methods_registry so that these can be accessed later.
        """
        self.implemented_components.append(SEARCH_TEXT_COMPONENT)
        self.translate_filter_methods_registry = dict()
        for method_name in dir(self):
            method = getattr(self, method_name)
            if hasattr(method, '_translates_filter_for_field_name'):
                self.translate_filter_methods_registry[method._translates_filter_for_field_name] = method

    def describe_textsearch(self):
        """
        Returns structured representation of component capabilities
        :return: tuple with (component name, dictionary with component capabilities)
        """
        return SEARCH_TEXT_COMPONENT, {
            SUPPORTED_FIELDS_DESCRIPTION_KEYWORD: self.get_supported_fields(),
            SUPPORTED_FILTERS_DESCRIPTION_KEYWORD: self.get_supported_filters(),
            SUPPORTED_SORT_OPTIONS_DESCRIPTION_KEYWORD: self.get_supported_sorting_criteria(),
        }

    def get_supported_sorting_criteria(self):
        """
        Checks which AudioCommons sorting criteria are supported by the third party service.
        These are the fields that raise an exception when calling 'process_s_query_parameter' with
        'raise_exception_if_unsupported' set to True.
        :return: list of available AudioCommons sorting criteria
        """
        supported_criteria = list()
        for option in SORT_OPTIONS:
            try:
                self.process_s_query_parameter(option, desc=True, raise_exception_if_unsupported=True)
                supported_criteria.append('-{0}'.format(option))
            except ACException:
                pass
            except NotImplementedError:
                # No sorting is supported at all
                return list()

            try:
                self.process_s_query_parameter(option, desc=False, raise_exception_if_unsupported=True)
                supported_criteria.append(option)
            except ACException:
                pass
            except NotImplementedError:
                # No sorting is supported at all
                return list()

        return supported_criteria

    @property
    def direct_filters_mapping(self):
        """
        Return a dictionary of Audio Commons filter names that can be directly mapped to
        service resource filters. 'directly mapped' means that the value for a given filter can be passed
        as specified using the Audio Commons filter syntax can be directly used to specify the same filter
        for the third party service, with the only difference of (probably) changing the field name. For example,
        if a third party seconds uses the time unit seconds to filter by duration, then there is no need to transform
        that value when interpreting an Audio Commons filter and passing it to the third party service. In this case
        the filter can be defined in the `direct_filters_mapping` function by adding an entry in the dictionary of the
        Audio Commons field name and the corresponding third party service field name. This works similar to
        `BaseACServiceSearchMixin.direct_fields_mapping` property.
        :return: dictionary mapping (keys are Audio Commons field names and values are services' resource field names)
        """
        return {}

    def get_supported_filters(self):
        """
        Checks which AudioCommons filters can be translated to the third party service filters.
        These are the filters defined with the decorator @translates_filter_for_field
        :return: list of available AudioCommons field names (fields equivalent to the filters)
        """
        return list(self.direct_filters_mapping.keys()) + list(self.translate_filter_methods_registry.keys())

    def translate_filter(self, ac_field_name, value):
        """
        Given an Audio Commons field name and a value for a filter (e.g. "ac:duration" and "3.5"), this method
        returns the corresponding field name and values that can be understood by a third party service. Following from
        the previous example, this method could return something like ("duration", 3500) if the field for "ac:duration"
        is named "duration" in the third party service and durations are specified in milliseconds instead of seconds.
        To perform this translation first we check if the field is available in
        self.direct_filters_mapping. If that is the case, this function simply returns the corresponding
        (key, value) tuple with the key being changed to the one specified in self.direct_filters_mapping.
        If field name is not available in self.direct_filters_mapping, then we check if it is available
        in the registry of translate filters for field methods self.translate_filter_methods_registry which is built
        when running self.conf_textsearch() (see ACServiceTextSearchMixin.conf_textsearch(self, *args).
        If a method for the ac_field_name exists in self.translate_filter_methods_registry we call it and
        return its response.
        If field does not exist in self.direct_filters_mapping or self.translate_filter_methods_registry
        we raise an exception to inform that filter for field could not be translated.
        :param ac_field_name: Audio Commons name of the field to filter
        :param value: value for the filter
        :return: (field_name, value) tuple with field_name and value translated to the third party service domain
        """
        try:
            if ac_field_name in self.direct_filters_mapping:
                return self.direct_filters_mapping[ac_field_name], value  # Do direct mapping
            return self.translate_filter_methods_registry[ac_field_name](value)  # Invoke translate method
        except KeyError:
            raise ACFilterParsingException('Filter for field \'{0}\' not supported'.format(ac_field_name))
        except ACFilterParsingException:
            raise
        except Exception as e:  # Use generic catch on purpose so we can properly notify the frontend
            raise ACFilterParsingException('Unexpected error processing filter for '
                                           'field \'{0}\' ({1}: {2})'.format(ac_field_name, e.__class__.__name__, e))

    def process_filter_element(self, elm, filter_list):
        """
        In the Audio Commons API filters are passed as a string which can represent complex structures. For instance
        a filter could be defined as "ac:format:wav AND ac:duration:[10,40]". ACServiceTextSearchMixin parses this
        string (see services.acservice.utils.parse_filter) and transforms it into a nested list of elements. This method
        takes one of this elements and processes it accordingly. To "process" a filter element means to first identify
        what kind of element it is. Elements can be:
            - a) a filter term like ("field_name", ":" "filter_value")
            - b) an operator like ("AND")
            - c) a more complex structure like (X, Y, Z) or (X, (Y, Z)
        Filter elements which are not "final " (complex structures) are processed recursively element by element.
        Filter elements which are final (filter terms or operators) are rendered calling the
        `ACServiceTextSearchMixin.render_filter_term` and `ACServiceTextSearchMixin.render_operator_term` methods,
        which are supposed to be overwritten by services which support filtering queries. Before rendering the filters,
        this method calls `ACServiceTextSearchMixin.translate_filter` to get the translated field names and values that
        are understood by the third party service.
        :param elm: filter element as returned by parser (will be of type pyparsing.ParseResults)
        :param filter_list: list of processed filter element that's recursively passed to process_filter_element
        :return: None (output must be read from filter_list, see `ACServiceTextSearchMixin.build_filter_string`)
        """

        def is_filter_term(parse_results):
            return len(parse_results) == 3 and parse_results[1] == ':'

        def is_operator(parse_results):
            return type(parse_results) == str and parse_results.upper() in ['AND', 'OR', 'NOT']

        def is_not_structure(parse_results):
            try:
                return parse_results[0].upper() == 'NOT'
            except Exception:
                return False

        if is_filter_term(elm):
            # If element is a key/value filter pair, render and add it to the filter list
            # Translate key and value for the ones the 3rd party service understands
            fkey = elm[0]
            fvalue = elm[2]
            if type(fvalue) == pyparsing.ParseResults and len(fvalue) == 2:
                # If filter is of type range, translate the values per separate
                key, value1 = self.translate_filter(fkey, fvalue[0])
                _, value2 = self.translate_filter(fkey, fvalue[1])
                value = (value1, value2)
            else:
                key, value = self.translate_filter(fkey, fvalue)

            kwargs = {'key': key}
            if type(value) in (int, float):  # Value is number
                kwargs.update({'value_number': value})
            elif type(value) is str:  # Value is text
                kwargs.update({'value_text': value})
            elif type(value) == tuple and len(value) == 2:  # Value is a range
                kwargs.update({'value_range': value})
            filter_list.append(self.render_filter_term(**kwargs))

        elif is_operator(elm):
            # If element is an operator, render and add it to the filter list
            filter_list.append(self.render_operator_term(elm.upper()))

        elif type(elm) == pyparsing.ParseResults:
            # If element is a more complex structure, walk it recursively and add precedence elements () if needed

            if not is_not_structure(elm):
                filter_list.append('(')
            for item in elm:
                self.process_filter_element(item, filter_list)
            if not is_not_structure(elm):
                filter_list.append(')')
        else:
            raise ACFilterParsingException

    def build_filter_string(self, filter_input_value):
        """
        This method gets a filter string defined using the Audio Commons filter string syntax and Audio Commons field
        names and values, and returns a filter string which uses the filtering syntax, filter names and compatible
        values of the individual third party service. Raises `ACFilterParsingException` if problems occur during filter
        parsing. For instance, an input filter like "ac:format:wav AND ac:duration:[2,10]" could be translated to
        something like "format=wav+duration=[2 TO 10]".
        :param filter_input_value: input filter string
        :return: output (translated) filter string
        """
        try:
            parsed_filter = parse_filter(filter_input_value)
        except pyparsing.ParseException:
            raise ACFilterParsingException('Could not parse filter: "{0}"'.format(filter_input_value))
        out_filter_list = list()
        self.process_filter_element(parsed_filter[0], out_filter_list)
        if out_filter_list[0] == '(':
            # If out filter list starts with an opening parenthesis, remove first and last positions ad both will
            # correspond to redundant parentheses
            out_filter_list = out_filter_list[1: -1]
        filter_string = ''.join(out_filter_list)
        return filter_string

    def text_search(self, context, q, f, s, common_search_params):
        """
        This function a search request to the third party service and returns a formatted json
        response as a dictionary if the response status code is 200 or raises an exception otherwise.

        Note that to implement text search services do not typically need to overwrite this method
        but the individual `process_x_query_parameter` methods.

        During processing of the response a number of warnings can be raised using the
        BaseACService.add_response_warning method. This warnings should contain additional
        relevant information regarding the request/response that will be returned in the aggregated
        response. For example, if a request wants to retrieve a number of metadata fields and one of these
        fields is not supported by the third party service, this will be recorded as a warning.
        We want to return the other supported fields but also a note that says that field X was not
        returned because it is not supported by the service.

        Common search parameters include:
        TODO: write common params when decided

        :param context: Dict with context information for the request (see api.views.get_request_context)
        :param q: textual input query
        :param f: query filter
        :param s: sorting criteria
        :param common_search_params: dictionary with other search parameters commons to all kinds of search
        :return: formatted text search response as dictionary
        """
        query_params = dict()

        # Process 'q' query parameter
        try:
            query_params.update(self.process_q_query_parameter(q))
        except NotImplementedError as e:
            self.add_response_warning(str(e))

        # Process 'f' parameter (if specified)
        if f is not None:
            try:
                query_params.update(self.process_f_query_parameter(f))
            except NotImplementedError as e:
                self.add_response_warning(str(e))

        # Process 's' parameter (if specified)
        if s is not None:
            try:
                desc = False
                if s.startswith('-'):
                    desc = True
                    s = s[1:]
                query_params.update(self.process_s_query_parameter(s, desc))
            except NotImplementedError as e:
                self.add_response_warning(str(e))

        # Process common search parameters
        query_params.update(self.process_common_search_params(common_search_params))

        # Add extra query parameters as returned by self.add_extra_search_query_params()
        # NOTE: parameters already present in query_params have preference and are not overwritten
        params_to_add = {key: value for key, value in self.add_extra_search_query_params().items()
                         if key not in query_params}
        query_params.update(params_to_add)

        # Send request and process response
        response = self.send_request(self.TEXT_SEARCH_ENDPOINT_URL, params=query_params)
        formatted_response = self.format_search_response(response, common_search_params, format=context['format'])
        return formatted_response

    # ***********************************************************************
    # The methods below are expected to be overwritten by individual services
    # ***********************************************************************

    def process_q_query_parameter(self, q):
        """
        Process contents of textual query input parameter and translate it to corresponding query parameter(s)
        for the third party service. Raise warnings using the BaseACService.add_response_warning method.
        The query parameters are returned as a dictionary where keys and values will be sent as keys and values of
        query parameters in the request to the third party service. Typically the returned query parameters dictionary
        will only contain one key/value pair.
        :param q: textual input query
        :return: query parameters dict
        """
        raise NotImplementedError("Parameter '{0}' not supported".format(QUERY_PARAM_QUERY))

    def process_f_query_parameter(self, f):
        """
        Process contents of query filter and translate it to corresponding query parameter(s)
        for the third party service. Raise warnings using the BaseACService.add_response_warning method.
        The query parameters are returned as a dictionary where keys and values will be sent as keys and values of
        query parameters in the request to the third party service. Typically the returned query parameters dictionary
        will only contain one key/value pair.
        :param f: query filter
        :return: query parameters dict
        """
        raise NotImplementedError("Parameter '{0}' not supported".format(QUERY_PARAM_FILTER))

    def render_filter_term(self, key, value_text=None, value_number=None, value_range=None):
        """
        This function gets a filter key (field name) and value pair (a filter term) and renders it as a string
        representing that filter term according to the third party service filtering syntax. The value can be a string,
        a number or a range, and will be passed to `value_text`, `value_number` or `value_range` accordingly. For
        example, for a given input key="format" and value_text="wav", this function might return the string "key:wav"
        if the third party service uses a syntax like "key:value" for filtering. Similarly, for a given input like
        key="duration" and value_range=(4,6), the output could be "duration:[4 TO 6]". Range values do not necessarily
        need to be of numbers, these could also be text.
        :param key: filter key (field name)
        :param value_text: value for the filter in case it is of type string (can be None)
        :param value_number: value for the filter in case it is of type int of float (can be None)
        :param value_range: value for the filter in case it is of type tuple (can be None).
        :return: string with the rendered filter term.
        """
        NotImplementedError("Service must implement method ACServiceTextSearchMixin.render_filter_term "
                            "to support filtering")

    def render_operator_term(self, operator):
        """
        Similarly to `ACServiceTextSearchMixin.render_filter_term`, this method takes as input an string representing an
        operator in the Audio Commons filter syntax domain, and returns the string corresponding to the same operator
        in the third party service domain. Audio Commons operators can be "AND", "OR" or "NOT".
        For example, for a given input operator="AND" this method might return " && " if filter terms are "ANDed" using
        spaces and the characters && in the third party service filter syntax.
        :param operator: string which can be "AND", "OR" or "NOT".
        :return: string with the corresponding operator in the third party service filter syntax
        """
        NotImplementedError("Service must implement method ACServiceTextSearchMixin.render_operator_term "
                            "to support filtering")

    def process_s_query_parameter(self, s, desc, raise_exception_if_unsupported=False):
        """
        Process contents of sort parameter and translate it to corresponding query parameter(s)
        for the third party service. Raise warnings using the BaseACService.add_response_warning method.
        The query parameters are returned as a dictionary where keys and values will be sent as keys and values of
        query parameters in the request to the third party service. Typically the returned query parameters dictionary
        will only contain one key/value pair.
        :param s: sorting method
        :param desc: use descending order
        :param raise_exception_if_unsupported: whether to raise an exception if desired criteria is unsupported
        :return: query parameters dict
        """
        raise NotImplementedError("Parameter '{0}' not supported".format(QUERY_PARAM_SORT))
