# Volatility
#
# Authors
# Toni
# CFX
# Eric
# Daniel Gracia Perez <daniel.gracia-perez@cfa-afti.fr>
#
# This file is part of Volatility.
#
# Volatility is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Volatility is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Volatility.  If not, see <http://www.gnu.org/licenses/>.
#

"""checkpstree example file"""
import os.path
import json
import volatility.win32.tasks as tasks
import volatility.utils as utils
import volatility.plugins.common as common
import volatility.cache as cache
import volatility.obj as obj
import volatility.debug as debug
from volatility.renderers.basic import Address, Hex
import volatility.plugins.vadinfo as vadinfo

#pylint: disable-msg=C0111

def _build_ps_tree(pslist):

    # Try to find a tree node which is parent to the passed process
    # (child) and attach it to it
    def attach_child(child, pstree):
        # At each root node of the current tree check if the current
        # process node is a child of it. If not a child of the root node,
        # try to see if it is a child of one of the root node children by
        # recursively calling the attach_child function.
        # If we were able to find a the parent of the process then return
        # True, otherwise False.
        # TODO: we could stop the loop if a parent was found.
        for parent in pstree:
            if parent['pid'] == child['ppid']:
                parent['children'].append(child)
                return True
            else:
                if attach_child(child, parent['children']):
                    return True
        return False

    # Create a tree node
    def create_ps_node(task):
        proc = {'pid': int(task.UniqueProcessId),
                'ppid': int(task.InheritedFromUniqueProcessId),
                'name': str(task.ImageFileName),
                'ctime': str(task.CreateTime),
                'proc': task,
                'children': []}
        peb = {'cmdline': None,
               'image_baseaddr': Address(0),
               'baseaddr': Address(0),
               'size': Hex(0),
               'basename': None,
               'fullname': None}
        vad = {'filename': '<No VAD>',
               'baseaddr': Address(0),
               'size': Hex(0),
               'protection': '<No VAD>',
               'tag': '<No VAD>'}
        if task.Peb:
            peb['cmdline'] = task.Peb.ProcessParameters.CommandLine
            mods = task.get_load_modules()
            for mod in mods:
                ext = os.path.splitext(str(mod.FullDllName))[1].lower()
                if ext == '.exe':
                    peb['image_baseaddr'] = Address(task.Peb.ImageBaseAddress)
                    peb['baseaddr'] = Address(mod.DllBase)
                    peb['size'] = Hex(0)
                    peb['basename'] = str(mod.BaseDllName)
                    peb['fullname'] = str(mod.FullDllName)
                    break
            vads = task.get_vads(vad_filter=task._mapped_file_filter)
            for entry, addr_space in vads:
                ext = ""
                vad_found = False
                if obj.Object("_IMAGE_DOS_HEADER",
                              offset=entry.Start,
                              vm=addr_space).e_magic != 0x5A4D:
                    continue
                if str(entry.FileObject.FileName or ''):
                    ext = os.path.splitext(str(entry.FileObject.FileName))[1]
                    ext = ext.lower()
                tmp_peb_iba = task.Peb.ImageBaseAddress
                if (ext == ".exe") or (entry.Start == tmp_peb_iba):
                    vad['filename'] = str(entry.FileObject.FileName)
                    vad['baseaddr'] = Address(entry.Start)
                    vad['size'] = Hex(entry.End - entry.Start)
                    tmp_vad_fp = entry.VadFlags.Protection.v()
                    tmp_vad_fp = vadinfo.PROTECT_FLAGS.get(tmp_vad_fp)
                    vad['protection'] = str(tmp_vad_fp or '')
                    vad['tag'] = str(entry.Tag or '')
                    vad_found = True
                    break
            if not vad_found:
                vad['filename'] = 'NA'
                vad['protection'] = 'NA'
                vad['tag'] = 'NA'
        proc['peb'] = peb
        proc['vad'] = vad
        return proc

    def add_ps(task, pstree):
        # create a tree node from the raw process
        proc = create_ps_node(task)
        # check if one of the root nodes in the current process tree is a
        # child of the node we have created, if so remove it from the tree
        # root and put it as a child of the created node
        for index, child in enumerate(pstree):
            if child['ppid'] == proc['pid']:
                proc['children'].append(child)
                del pstree[index]
        # try to attach the current node in one of the nodes of the current
        # tree, otherwise put it in the root of the tree
        if not attach_child(proc, pstree):
            pstree.append(proc)

    pstree = []
    for task in iter(pslist):
        add_ps(task, pstree)
    return pstree


# class CheckPSTree(pstree.PSTree):
class CheckPSTree(common.AbstractWindowsCommand):
    """Print process list as a tree and perform check on common anomalies"""
    # Declare meta information associated with this plugin
    meta_info = {
        'author': ['Toni', 'CFX', 'Eric Jouenne', 'Daniel Gracia Perez'],
        'copyright': 'Copyright (c) 2018 ' +
                     'Toni, ' +
                     'CFX, ' +
                     'Eric Jouenne and ' +
                     'Daniel Gracia Perez',
        'contact': 'daniel.gracia-perez@cfa-afti.fr',
        'license': 'GNU General Public License 2.0',
        'url': 'https://github.com',
        'version': '1.0'}

    text_sort_column = "Pid"

    def __init__(self, config, *args, **kwargs):
        common.AbstractWindowsCommand.__init__(self, config, *args, **kwargs)
        config.add_option(
            'CONFIG', short_option='c', default=None,
            help='Full path to checkpstree configuration file',
            action='store', type='str')
        self._check_config = {}

    def render_text(self, outfd, data):

        def print_procs(indent, pstree):
            for proc in pstree:
                peb = proc['peb']['fullname']
                vad = proc['vad']['filename']
                outfd.write("{}{} {} peb:{} vad:{}\n".format(
                    '.' * indent, proc['pid'], proc['name'],
                    peb if peb is not None else '<None>',
                    vad if vad is not None else '<None>'))
                print_procs(indent + 1, proc['children'])

        def print_unique_names(entries):
            outfd.write("Unique Names Check\n")
            self.table_header(outfd,
                              [("Name", "<50"),
                               ("Count", ">6"),
                               ("Pass", ">6")])
            for entry in entries:
                self.table_row(outfd,
                               entry['name'],
                               entry['count'],
                               'True' if entry['pass'] else 'False')
            outfd.write("\n")

        def print_reference_parents(entries):
            outfd.write("Reference Parents Check\n")
            self.table_header(outfd,
                              [('Name', '<50'),
                               ('pid', '>6'),
                               ('Parent', '<50'),
                               ('ppid', '>6'),
                               ('Pass', '>6'),
                               ('Expected Parent', '<50')])
            ref_parents = self._check_config['reference_parents']
            for entry in entries:
                expected = ref_parents[entry['name']]
                self.table_row(outfd,
                               entry['name'],
                               entry['pid'],
                               entry['parent'],
                               entry['ppid'],
                               'True' if entry['pass'] else 'False',
                               expected)
            outfd.write("\n")

        def print_peb_fullname(entries):
            outfd.write("Path(PEB) Check\n")
            self.table_header(outfd,
                              [('pid', '>6'),
                               ('Name', '<20'),
                               ('Path', '<40'),
                               ('Pass', '>6'),
                               ('Expected Path', '<40')])
            for entry in entries:
                expected = self._check_config['peb_fullname'][entry['name']]
                self.table_row(outfd,
                               entry['pid'],
                               entry['name'],
                               entry['fullname'],
                               'True' if entry['pass'] else 'False',
                               expected)
            outfd.write("\n")

        def print_vad_filename(entries):
            outfd.write("Path(VAD) Check\n")
            self.table_header(outfd,
                              [('pid', '>6'),
                               ('Name', '<20'),
                               ('Path', '<40'),
                               ('Pass', '>6'),
                               ('Expected Path', '<40')])
            for entry in entries:
                expected = self._check_config['vad_filename'][entry['name']]
                self.table_row(outfd,
                               entry['pid'],
                               entry['name'],
                               entry['filename'],
                               'True' if entry['pass'] else 'False',
                               expected)
            outfd.write("\n")

        pstree = data['pstree']
        check = data['check']
        outfd.write("""
===============================================================================
CheckPSTree analysis report
""")
        outfd.write("PSTree\n")
        print_procs(0, pstree)
        outfd.write("\n")
        if 'unique_names' in check:
            print_unique_names(check['unique_names'])
        if 'reference_parents' in check:
            print_reference_parents(check['reference_parents'])
        if 'peb_fullname' in check:
            print_peb_fullname(check['peb_fullname'])
        if 'vad_filename' in check:
            print_vad_filename(check['vad_filename'])

    def check_unique_names(self, pstree):
        def count_occurrences(name, pstree):
            count = 0
            for proc in pstree:
                if proc['name'] == name:
                    count = count + 1
                count = count + count_occurrences(name, proc['children'])
            return count

        report = []
        for name in self._check_config['unique_names']:
            count = count_occurrences(name, pstree)
            ret = {'name': name,
                   'count': count,
                   'pass': True if count <= 1 else False}
            report.append(ret)
        return report

    def check_reference_parents(self, pstree):
        report = []
        ref_parents = self._check_config['reference_parents']

        def check_reference_parent(parent, pstree):
            for proc in pstree:
                if proc['name'] in ref_parents.keys():
                    report.append({
                        'pid': proc['pid'],
                        'ppid': proc['ppid'],
                        'name': proc['name'],
                        'parent': parent,
                        'pass': parent == ref_parents[proc['name']]})
                check_reference_parent(str(proc['proc'].ImageFileName),
                                       proc['children'])
        for proc in pstree:
            check_reference_parent(proc['name'], proc['children'])
        return report

    def find_nodes(self, pstree, match_func):
        nodes = []
        for proc in pstree:
            if match_func(proc):
                nodes.append(proc)
            nodes.extend(self.find_nodes(proc['children'], match_func))
        return nodes

    def check_peb_fullname(self, pstree):
        report = []
        peb_entries = self._check_config['peb_fullname']
        for name, path in peb_entries.iteritems():
            match_func = lambda node, match=name: node['name'] == match
            nodes = self.find_nodes(pstree, match_func)
            for node in nodes:
                report.append({
                    'pid': node['pid'],
                    'ppid': node['ppid'],
                    'name': node['name'],
                    'fullname': node['peb']['fullname'],
                    'pass': node['peb']['fullname'].lower() == path.lower()})
        return report

    def check_vad_filename(self, pstree):
        report = []
        vad_entries = self._check_config['vad_filename']
        for name, path in vad_entries.iteritems():
            match_func = lambda node, match=name: node['name'] == match
            nodes = self.find_nodes(pstree, match_func)
            for node in nodes:
                report.append({
                    'pid': node['pid'],
                    'ppid': node['ppid'],
                    'name': node['name'],
                    'filename': node['vad']['filename'],
                    'pass': node['vad']['filename'] == path})
        return report

    # Perform plugin checks. Currently it includes:
    # - unique_names
    # - reference_parents
    def checking(self, pstree):
        reports = {}
        # For every check in the configuration perform the correspondent check.
        # For each configured check create a report.
        if 'unique_names' in self._check_config:
            report = self.check_unique_names(pstree)
            reports['unique_names'] = report
        if 'reference_parents' in self._check_config:
            reports['reference_parents'] = self.check_reference_parents(pstree)
        if 'peb_fullname' in self._check_config:
            reports['peb_fullname'] = self.check_peb_fullname(pstree)
        if 'vad_filename' in self._check_config:
            reports['vad_filename'] = self.check_vad_filename(pstree)
        return reports

    # Check the configuration files
    # If no configuration was provided we try to load a configuration file from
    # <plugin_path>/checkpstree_configs/<profile>.json
    # profile being the value in self._config.PROFILE
    # If the user specifies another configuration file in self._config.CONFIG
    # then the user specified file is loaded.
    def check_config(self):
        config_filename = self._config.CONFIG
        if config_filename is None:
            profile = self._config.PROFILE + ".json"
            path = self._config.PLUGINS
            config_filename = os.path.join(path,
                                           "checkpstree_configs",
                                           profile)
        # check config file exists and it's a file
        if not os.path.exists(config_filename):
            debug.error("Configuration file '{}' does not exist".format(
                config_filename))
        if not os.path.isfile(config_filename):
            debug.error(
                "Configuration filename '{}' is not a regular file".format(
                    config_filename))
        # open configuration file and parse contents
        try:
            config_file = open(config_filename)
        except:
            debug.error("Couldn't open configuration file '{}'".format(
                config_filename))
        try:
            config = json.load(config_file)
        except:
            debug.error("Couldn't load json configuration from '{}'".format(
                config_filename))
        # TODO: could be nice to make some checking on the configuration format
        #       to verify that it has the supported fields and so on
        self._check_config = config['config']

    @cache.CacheDecorator(lambda self: "tests/checkpstree/verbose={0}".format(
        self._config.VERBOSE))
    def calculate(self):
        # Check the plugin configuration
        self.check_config()
        # Get the list of process
        addr_space = utils.load_as(self._config)
        pslist = tasks.pslist(addr_space)
        # A tree structure (with multiple roots) is created from the processes
        # list. This structure will be used to perform the plugin checks.
        pstree = _build_ps_tree(pslist)
        # Perform plugin checks
        check_reports = self.checking(pstree)
        # Return output data (data that can be printed in the console)
        return {"pstree": pstree, "check": check_reports}
