from collections import defaultdict
import os

from cStringIO import StringIO
import cy_ast
import version


UNDEFINED = '__UNDEFINED__'


CODE_HEADER = """\
# This code was automatically generated by CWrap %s.

""" % version.version()


IGNORED_TYPES = (cy_ast.Ignored,)
MODIFIER_TYPES = (cy_ast.PointerType, cy_ast.ArrayType, cy_ast.CvQualifiedType)
REFERENCE_TYPES = (cy_ast.PointerType, cy_ast.ArrayType)
NAMED_TYPES = (cy_ast.Struct, cy_ast.Enumeration, cy_ast.Union, 
               cy_ast.FundamentalType, cy_ast.Typedef) 


class Code(object):

    def __init__(self):
        self._io = StringIO()
        self._indent_level = 0
        self._indentor = '    '
        self._imports = defaultdict(set)
        self._imports_from = defaultdict(lambda: defaultdict(set))
        self._cimports = defaultdict(set)
        self._cimports_from = defaultdict(lambda: defaultdict(set))

    def indent(self, n=1):
        self._indent_level += n

    def dedent(self, n=1):
        self._indent_level -= n

    def write_i(self, code):
        indent = self._indentor * self._indent_level
        self._io.write('%s%s' % (indent, code))

    def write(self, code):
        self._io.write(code)

    def add_import(self, module, as_name=None):
        self._imports[module].add(as_name)

    def add_import_from(self, module, imp_name, as_name=None):
        self._imports_from[module][imp_name].add(as_name)

    def add_cimport(self, module, as_name=None):
        self._cimports[module].add(as_name)
    
    def add_cimport_from(self, module, imp_name, as_name=None):
        if as_name is not None:
            self._cimports_from[module][imp_name].add(as_name)
        else:
            self._cimports_from[module][imp_name]

    def _gen_imports(self):
        import_lines = []

        # cimports
        cimport_items = sorted( self._cimports.iteritems() )
        for module, as_names in cimport_items:
            if as_names:
                for name in sorted(as_names):
                    import_lines.append('cimport %s as %s' % (module, name))
            else:
                import_lines.append('cimport %s' % module)

        # cimports from
        cimport_from_items = sorted( self._cimports_from.iteritems() )
        for module, impl_dct in cimport_from_items:
            sub_lines = []
            for impl_name, as_names in sorted(impl_dct.iteritems()):
                if as_names:
                    for name in sorted(as_names):
                        sub_lines.append('%s as %s' % (impl_name, name))
                else:
                    sub_lines.append(impl_name)
            sub_txt = ', '.join(sub_lines)
            import_lines.append('from %s cimport %s' % (module, sub_txt))

        # cimports
        import_items = sorted( self._imports.iteritems() )
        for module, as_names in import_items:
            if as_names:
                for name in sorted(as_names):
                    import_lines.append('import %s as %s' % (module, name))
            else:
                import_lines.append('import %s' % module)

        # cimports from
        import_from_items = sorted( self._imports_from.iteritems() )
        for module, impl_dct in import_from_items:
            sub_lines = []
            for impl_name, as_names in sorted(impl_dct.iteritems()):
                if as_names:
                    for name in sorted(as_names):
                        sub_lines.append('%s as %s' % (impl_name, name))
                else:
                    sub_lines.append(impl_name)
            sub_txt = ', '.join(sub_lines)
            import_lines.append('from %s import %s' % (module, sub_txt))

        return '\n'.join(import_lines)
                    
    def code(self):
        imports = self._gen_imports()
        if imports:
            res = CODE_HEADER + imports + '\n\n' + self._io.getvalue()
        else:
            res = CODE_HEADER + self._io.getvalue()
        return res


class ExternRenderer(object):
    """ An ast visitor which generates all of the `cdef extern from`
    declarations for the ast. 

    """
    def __init__(self):
        self.context = []
        self.code = None
        self.header_path = None
        self.config = None
        self.toplevel_ns = None

    #--------------------------------------------------------------------------
    # Dispatch methods
    #--------------------------------------------------------------------------
    def render(self, namespace, header_path, config):
        self.context = []
        self.code = Code()
        self.header_path = header_path
        self.config = config
        self.toplevel_ns = namespace

        # filter for the items that are in this header
        # they are already ordered by their appearance
        items = namespace.members
        toplevel = []
        for item in items:
            if item.location and (item.location[0] == header_path):
                toplevel.append(item)

        header_name = self.config.header(header_path).header_name
        self.code.write_i('cdef extern from "%s":\n\n' % header_name)
        self.code.indent()
        if toplevel:
            for item in toplevel:
                self.visit(item)
        else:
            self.code.write_i('pass')
        self.code.dedent()

        return self.code.code()
    
    def visit(self, node):
        self.context.append(node)
        method = 'visit_' + node.__class__.__name__
        visitor = getattr(self, method, self.unhandled_node)
        visitor(node)
        self.context.pop()

    def unhandled_node(self, node):
        print 'Unhandled node in extern renderer: `%s`' % node
    
    #--------------------------------------------------------------------------
    # Top level node visitors
    #--------------------------------------------------------------------------
    def visit_Typedef(self, typedef):
        typ = typedef.typ
        name = typedef.name
        typ_name, name = self.render_type(typ, name)
        self.code.write_i('ctypedef %s %s\n\n' % (typ_name, name))
   
    def visit_Struct(self, struct):
        name = struct.name
        if struct.opaque:
            self.code.write_i('cdef struct %s\n' % name)
        else:
            self.code.write_i('cdef struct %s:\n' % name)
            self.code.indent()
            for field in struct.members:
                if isinstance(field, cy_ast.Ignored):
                    continue
                typ_name, name = self.render_field(field)
                self.code.write_i('%s %s\n' % (typ_name, name))
            self.code.dedent()
        self.code.write('\n')
    
    def visit_Union(self, union):
        name = union.name
        if union.opaque:
            self.code.write_i('cdef union %s\n' % name)
        else:
            self.code.write_i('cdef union %s:\n' % name)
            self.code.indent()
            for field in union.members:
                if isinstance(field, cy_ast.Ignored):
                    continue
                typ_name, name = self.render_field(field)
                self.code.write_i('%s %s\n' % (typ_name, name))
            self.code.dedent()
        self.code.write('\n')

    def visit_Enumeration(self, enum):
        name = enum.name
        if enum.opaque:
            if name is None:
                self.code.write_i('cdef enum\n')
            else:
                self.code.write_i('cdef enum %s\n' % name)
        else:
            if name is None:
                self.code.write_i('cdef enum:\n')
            else:
                self.code.write_i('cdef enum %s:\n' % name)
            self.code.indent()
            for value in enum.values:
                if isinstance(value, cy_ast.Ignored):
                    continue
                value_str = self.render_enum_value(value)
                self.code.write_i('%s\n' % value_str)
            self.code.dedent()
        self.code.write('\n')

    def visit_Function(self, function):
        args = '(' + self.render_arguments(function.arguments) + ')'
        name = function.name + args
        typ_name, name = self.render_returns(function.returns, name)
        self.code.write_i('%s %s\n\n' % (typ_name, name))

    def visit_Variable(self, var):
        name = var.name
        typ = var.typ
        typ_name, name = self.render_type(typ, name)
        self.code.write_i('%s %s\n\n' % (typ_name, name))

    def visit_Ignored(self, node):
        pass
   
    #--------------------------------------------------------------------------
    # Auxiliary renderers
    #--------------------------------------------------------------------------
    def render_type(self, typ, name):
        """ Takes a type node and name and returns the typ_name, name
        pair modified appropriately.

        """
        if isinstance(typ, MODIFIER_TYPES):
            typ, name = self.apply_modifier(typ, name)

        if isinstance(typ, NAMED_TYPES):
            typ_name = typ.name
        elif isinstance(typ, cy_ast.FunctionType):
            typ_name, name = self.render_function_type(typ, name)
        else:
            print 'Unhandled type in render_type: `%s`.' % typ
            typ_name = UNDEFINED
        
        return typ_name, name

    def render_enum_value(self, enum_value):
        return enum_value.name
    
    def render_field(self, field):
        typ = field.typ
        name = field.name
        return self.render_type(typ, name)
            
    def render_returns(self, returns, name):
        """ Renders a function return value from the given node. 
        The name of the function must also be given *including the 
        argument list* so that modifiers can be rendered properly
        (i.e. pointers to arrays). The return value is a tuple of
        typ_name, name.

        """
        return self.render_type(returns, name)
            
    def render_function_type(self, function_type, name):
        """ Renders a function type from the given function type node 
        and name. Returns type_name, name where typename is the return 
        type of the function, and name is the balance of the function
        type declaration.

        """
        args = '(' + self.render_arguments(function_type.arguments) + ')'
        name = '(' + name + ')' + args
        return self.render_returns(function_type.returns, name)
        
    def render_arguments(self, arguments):
        """ Renders an argument list from a given list of argument
        nodes. The return value is a comma delimited string.

        """
        res_args = []
        for arg in arguments:
            if isinstance(arg, cy_ast.Ignored):
                continue
            
            typ = arg.typ
            name = arg.name
             
            typ_name, name = self.render_type(typ, name)

            if name is not None and '*' in name:
                allow_void = True
            else:
                allow_void = False
                        
            # Cython doesn't use void arguments
            if typ_name == 'void' and not allow_void:
                arg_str = ''
            elif not name:
                arg_str ='%s' % typ_name
            else:
                arg_str = '%s %s' % (typ_name, name)
            
            res_args.append(arg_str)
        
        return ', '.join(res_args)
    
    def apply_modifier(self, typ, name):
        """ Applies pointer and array modifiers to a name. The typ
        node should be a PointerType, ArrayType, or CvQualifiedType. 
        The return value is the underlying typ node which is pointed
        to and the name modified by the appropriate declarations.

        """
        # flatten the tree of pointers/arrays ignoring CvQualifiedType's
        # (const and volatile)
        stack = []
        while isinstance(typ, MODIFIER_TYPES):
            if isinstance(typ, REFERENCE_TYPES):
                stack.append(typ)
            typ = typ.typ
        
        if name is None:
            name = ''
        
        # As we iterate the stack, we apply parens when the type of the 
        # stack node switches from Pointer to array or vice versa
        for i, node in enumerate(stack):
            if i > 0:
                if not isinstance(node, type(stack[i - 1])):
                    name = '(' + name + ')'
            if isinstance(node, cy_ast.PointerType):
                name = '*' + name
            else:
                max = node.max
                if max is None:
                    dim = ''
                else:
                    dim = str(max + 1)
                name = name + ('[%s]' % dim)  
     
        return typ, name


