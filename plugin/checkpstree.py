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
# from volatility import renderers
# from volatility.renderers.basic import Address

import volatility.win32.tasks as tasks
import volatility.utils as utils
# import volatility.plugins.common as common
import volatility.cache as cache
import volatility.obj as obj
import volatility.debug as debug
import volatility.plugins.pstree as pstree
from volatility.renderers.basic import Address,Hex
import volatility.plugins.vadinfo as vadinfo
import copy
import os.path
import json

#pylint: disable-msg=C0111

class CheckPSTree(pstree.PSTree):
    """Print process list as a tree and perform check on common anomalies"""
    # Declare meta information associated with this plugin
    meta_info = {
        'author': [ 'Toni', 'CFX', 'Eric Jouenne', 'Daniel Gracia Perez' ],
        'copyright': 'Copyright (c) 2018 Toni, CFX, Eric Jouenne and Daniel Gracia Perez',
        'contact': 'daniel.gracia-perez@cfa-afti.fr',
        'license': 'GNU General Public License 2.0',
        'url': 'https://github.com',
        'version': '1.0'}

    text_sort_column = "Pid"

    def __init__(self, config, *args, **kwargs):
        pstree.PSTree.__init__(self, config, *args, **kwargs)
        config.add_option('CONFIG', short_option='c', default=None,
                help = 'Full path to checkpstree configuration file',
                action='store', type='str')

    def render_text(self, outfd, data):
        pstree.PSTree.render_text(self, outfd, data["pstree"])
        check_data = data["check"]
        outfd.write("""
===============================================================================
Analysis report
""")
        def printProcs(indent, pstree):
            for p in pstree:
                outfd.write("{}{} {} {} {}\n".format('.' * indent, p['pid'], p['name'],
                    p['peb']['fullname'] if p['peb']['fullname'] is not None else '<None>',
                    p['vad']['filename'] if p['vad']['filename'] is not None else '<None>'))
                printProcs(indent + 1, p['children'])

        def printUniqueNames(entries):
            outfd.write("Unique Names Check\n")
            self.table_header(outfd,
                    [("Name", "<50"),
                     ("Count", ">6"),
                     ("Pass", ">6")])
            for e in entries:
                self.table_row(outfd,
                        e['name'],
                        e['count'],
                        'True' if e['pass'] else 'False')
            outfd.write("\n")

        def printReferenceParents(entries):
            outfd.write("Reference Parents Check\n")
            self.table_header(outfd,
                    [('Name', '<50'),
                        ('pid', '>6'),
                        ('Parent', '<50'),
                        ('ppid', '>6'),
                        ('Pass', '>6'),
                        ('Expected Parent', '<50')])
            for e in entries:
                self.table_row(outfd,
                    e['name'],
                    e['pid'],
                    e['parent'],
                    e['ppid'],
                    'True' if e['pass'] else 'False',
                    self._check_config['reference_parents'][e['name']]
                    )
            outfd.write("\n")

        outfd.write("PSTree\n")
        printProcs(0, check_data['pstree'])
        outfd.write("\n")
        check = check_data['check']
        if 'unique_names' in check:
            printUniqueNames(check['unique_names'])
        if 'reference_parents' in check:
            printReferenceParents(check['reference_parents'])


    def buildPsTree(self, pslist):

        def attachChild(child, pstree):
            for parent in pstree:
                if parent['pid'] == child['ppid']:
                    parent['children'].append(child)
                    return True
                else:
                    if attachChild(child, parent['children']):
                        return True
            return False

        def addPs(task, pstree):
            proc = {'pid': int(task.UniqueProcessId),
                    'ppid': int(task.InheritedFromUniqueProcessId),
                    'name': str(task.ImageFileName),
                    'ctime': str(task.CreateTime),
                    'proc': task,
                    'children': []}
            proc_cmdline = None
            proc_basename = None
            proc_fullname = None
            vad_filename = '<No VAD>'
            vad_baseaddr = Address(0)
            vad_size = Hex(0)
            vad_protection = '<No VAD>'
            vad_tag = '<No VAD>'
            if task.Peb:
                debug.info("{} {} has Peb".format(proc['pid'], proc['name']))
                proc_cmdline = task.Peb.ProcessParameters.CommandLine
                mods = task.get_load_modules()
                for mod in mods:
                    ext = os.path.splitext(str(mod.FullDllName))[1].lower()
                    if ext == '.exe':
                        proc_basename = str(mod.BaseDllName)
                        proc_fullname = str(mod.FullDllName)
                        break
                for vad, addr_space in task.get_vads(vad_filter = task._mapped_file_filter):
                    ext = ""
                    vad_found = False
                    if obj.Object("_IMAGE_DOS_HEADER", offset = vad.Start, vm = addr_space).e_magic != 0x5A4D:
                        continue
                    if str(vad.FileObject.FileName or ''):
                        ext = os.path.splitext(str(vad.FileObject.FileName))[1].lower()
                    if (ext == ".exe") or (vad.Start == task.Peb.ImageBaseAddress):
                        vad_filename =  str(vad.FileObject.FileName)
                        debug.info("VAD {}".format(vad_filename))
                        vad_baseaddr = Address(vad.Start)
                        vad_size = Hex(vad.End - vad.Start)
                        vad_protection = str(vadinfo.PROTECT_FLAGS.get(vad.VadFlags.Protection.v()) or '')
                        vad_tag = str(vad.Tag or '')
                        vad_found = True
                        break
                if vad_found == False:
                    vad_filename = 'NA'
                    vad_baseaddr = Address(0)
                    vad_size = Hex(0)
                    vad_protection = 'NA'
                    vad_tag = 'NA'
            else:
                debug.info("{} {} has no Peb".format(proc['pid'], proc['name']))
            proc['peb'] = {
                    'cmdline': proc_cmdline,
                    'basename': proc_basename,
                    'fullname': proc_fullname}
            proc['vad'] = {'filename': vad_filename,
                    'baseaddr': vad_baseaddr,
                    'size': vad_size,
                    'protection': vad_protection,
                    'tag': vad_tag}
            for index, child in enumerate(pstree):
                if child['ppid'] == proc['pid']:
                    proc['children'].append(child)
                    del pstree[index]
            if not attachChild(proc, pstree):
                pstree.append(proc)

        pstree = []
        for task in pslist:
            addPs(task, pstree)
        return pstree


    def checkUniqueNames(self, pstree):
        def countOcurrences(name, pstree):
            count = 0
            for ps in pstree:
                if ps['name'] == name:
                    count = count + 1
                count = count + countOcurrences(name, ps['children'])
            return count

        report = []
        for name in self._check_config['unique_names']:
            count = countOcurrences(name, pstree)
            ret = {'name': name,
                    'count': count,
                    'pass': True if count <= 1 else False}
            report.append(ret)
        return report


    def checkReferenceParents(self, pstree):
        report = []
        ref_parents = self._check_config['reference_parents']
        def checkReferenceParent(parent, pstree):
            for ps in pstree:
                if ps['name'] in ref_parents.keys():
                    report.append({
                        'pid': ps['pid'],
                        'ppid': ps['ppid'],
                        'name': ps['name'],
                        'parent': parent,
                        'pass': parent == ref_parents[ps['name']]})
                checkReferenceParent(str(ps['proc'].ImageFileName),
                    ps['children'])
        for ps in pstree:
            checkReferenceParent(ps['name'], ps['children'])
        return report


    def checking(self, pslist):
        pstree = self.buildPsTree(pslist)
        check = {}
        if self._check_config['unique_names']:
            report = self.checkUniqueNames(pstree)
            check['unique_names'] = report
        if self._check_config['reference_parents']:
            check['reference_parents'] = self.checkReferenceParents(pstree)
        return {'pstree': pstree, 'check': check}


    # Check the configuration files
    # If no configuration was provided we try to load a configuration file from
    # <plugin_path>/checkpstree_configs/<profile>.json
    # profile being the value in self._config.PROFILE
    # If the user specifies another configuration file in self._config.CONFIG
    # then the user specified file is loaded.
    def checkConfig(self):
        config_filename = self._config.CONFIG
        if config_filename is None:
            profile = self._config.PROFILE + ".json"
            path = self._config.PLUGINS
            config_filename = os.path.join(path, "checkpstree_configs", profile)
        # check config file exists and it's a file
        if not os.path.exists(config_filename):
            debug.error("Configuration file '{}' does not exist".format(
                config_filename))
        if not os.path.isfile(config_filename):
            debug.error("Configuration filename '{}' is not a regular file".format(
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


    @cache.CacheDecorator(lambda self: "tests/checkpstree/verbose={0}".format(self._config.VERBOSE))
    def calculate(self):
        self.checkConfig()
        psdict = pstree.PSTree.calculate(self)
        addr_space = utils.load_as(self._config)
        check_data = self.checking(tasks.pslist(addr_space))
        return { "pstree": psdict, "check": check_data }
