import logging
import os.path
import random
import fnmatch
from functools import partial

from Qt import QtCore, QtWidgets, QtGui
from pxr import Usd, Sdf, Ar

import utils
from vendor.Nodz import nodz_main
from . import text_view

import re
from pprint import pprint


digitSearch = re.compile(r'\b\d+\b')

reload(text_view)

reload(nodz_main)

logger = logging.getLogger('usd-dependency-graph')
logger.setLevel(logging.DEBUG)
if not len(logger.handlers):
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)
logger.propagate = False


class DependencyWalker(object):
    def __init__(self, usdfile):
        self.usdfile = usdfile
        self.stage = None
        
        logger.info('DependencyWalker'.center(40, '-'))
        logger.info('loading usd file: {}'.format(self.usdfile))
        self.nodes = {}
        self.edges = []
    
    
    def start(self):
        self.nodes = {}
        self.edges = []
        self.init_edges = []
        self.stage = None
        
        self.stage = Usd.Stage.Open(self.usdfile)
        rootLayer = self.stage.GetRootLayer()
        
        info = {}
        info['mute'] = False
        info['online'] = os.path.isfile(self.usdfile)
        info['path'] = self.usdfile
        info['type'] = 'layer'
        self.nodes[self.usdfile] = info
        
        self.walkStageLayers(rootLayer)
        self.walkStagePrims(self.usdfile)
        # raise RuntimeError("poo")
    
    
    def walkStageLayers(self, layer, level=1):
        """
        Recursive function to loop through a layer's external references
        
        :param layer: SdfLayer
        :param level: current recursion depth
        """
        
        id = '-' * (level)
        layer_path = layer.realPath
        # print id, 'layer: ', layer_path
        layer_basepath = os.path.dirname(layer_path)
        # print id, 'references:'
        # print 'refs', layer.GetExternalReferences()
        count = 0
        
        for ref in layer.GetExternalReferences():
            if not ref:
                # sometimes a ref can be a zero length string. whyyyyyyyyy?
                # seeing this in multiverse esper_room example
                continue
            
            refpath = os.path.normpath(os.path.join(layer_basepath, ref))
            # print id, refpath
            # if self.stage.IsLayerMuted(ref):
            #     print 'muted layer'
            # print 'anon?', Sdf.Layer.IsAnonymousLayerIdentifier(ref)
            
            # if you wanna construct a full path yourself
            # you can manually load a SdfLayer like this
            sub_layer = Sdf.Layer.Find(refpath)
            
            # or you can use FindRelativeToLayer to do the dirty work
            # seems to operate according to the composition rules (variants blah blah)
            # ie, it *may* not return a layer if the stage is set to not load that layer
            # sub_layer = Sdf.Layer.FindRelativeToLayer(layer, ref)
            
            online = True
            if sub_layer:
                child_count = self.walkStageLayers(sub_layer, level=level + 1)
            if not os.path.isfile(refpath):
                online = False
                # print "NOT ONLINE", ref
            
            if not refpath in self.nodes:
                count += 1
                info = {}
                info['mute'] = self.stage.IsLayerMuted(ref)
                info['online'] = online
                info['path'] = refpath
                info['type'] = 'layer'
                
                self.nodes[refpath] = info
            
            if not [layer_path, refpath] in self.init_edges:
                self.init_edges.append([layer_path, refpath])
        
        # print 'SUBLAYERS'
        # print layer.subLayerPaths
        for ref in layer.subLayerPaths:
            if not ref:
                # going to guard against zero length strings here too
                continue
            
            refpath = os.path.normpath(os.path.join(layer_basepath, ref))
            
            # if self.stage.IsLayerMuted(ref):
            #     print 'muted layer'
            sub_layer = Sdf.Layer.Find(refpath)
            online = True
            if sub_layer:
                child_count = self.walkStageLayers(sub_layer, level=level + 1)
            if not os.path.isfile(refpath):
                online = False
                # print "NOT ONLINE", ref
            
            if not refpath in self.nodes:
                count += 1
                info = {}
                info['mute'] = self.stage.IsLayerMuted(ref)
                info['online'] = online
                info['path'] = refpath
                info['type'] = 'sublayer'
                
                self.nodes[refpath] = info
            
            if not [layer_path, refpath] in self.init_edges:
                self.init_edges.append([layer_path, refpath])
        
        return count
    
    
    def walkStagePrims(self, usdfile):
        # print 'test'.center(40, '-')
        stage = Usd.Stage.Open(usdfile)
        
        for prim in stage.TraverseAll():
            # print(prim.GetPath())
            
            # from the docs:
            """Return a list of PrimSpecs that provide opinions for this prim (i.e.
            the prim's metadata fields, including composition metadata).
             specs are ordered from strongest to weakest opinion."""
            primStack = prim.GetPrimStack()
            for spec in primStack:
                if spec.hasPayloads:
                    payloadList = spec.payloadList
                    for itemlist in [payloadList.appendedItems, payloadList.explicitItems,
                                     payloadList.addedItems,
                                     payloadList.prependedItems, payloadList.orderedItems]:
                        if itemlist:
                            for payload in itemlist:
                                payload_path = payload.assetPath
                                
                                # print payload, payload_path
                                with Ar.ResolverContextBinder(stage.GetPathResolverContext()):
                                    resolver = Ar.GetResolver()
                                    # we resolve the payload path relative to the primSpec layer path (layer.identifier)
                                    # far more likely to be correct. i hope
                                    resolvedpath = resolver.AnchorRelativePath(spec.layer.identifier, payload_path)
                                    # print 'payload resolvedpath', resolvedpath
                                    
                                    info = {}
                                    info['online'] = os.path.isfile(resolvedpath)
                                    info['path'] = resolvedpath
                                    info['type'] = 'payload'
                                    
                                    self.nodes[resolvedpath] = info
                                    if spec.layer.identifier != resolvedpath:
                                        if not [spec.layer.identifier, resolvedpath, 'payload'] in self.edges:
                                            self.edges.append([spec.layer.identifier, resolvedpath, 'payload'])
                
                # the docs say there's a HasSpecializes method
                # no, there is not. at least in this build of houdini 18.0.453
                # if spec.HasSpecializes:
                # let's just ignore specialize for the time being
                """
                specializesList = spec.specializesList
                spec_paths = []
                for itemlist in [specializesList.appendedItems, specializesList.explicitItems,
                                 specializesList.addedItems,
                                 specializesList.prependedItems, specializesList.orderedItems]:
                    if itemlist:
                        for specialize in itemlist:
                            specialize_path = specialize.assetPath
                            with Ar.ResolverContextBinder(stage.GetPathResolverContext()):
                                resolver = Ar.GetResolver()
                                resolvedpath = resolver.AnchorRelativePath(spec.layer.identifier, specialize_path)
                                spec_paths.append(resolvedpath)
                                ret.append(resolvedpath)

                if spec_paths:
                    print 'specializesList', spec.specializesList

                """
                
                # references operate the same to payloads
                if spec.hasReferences:
                    reflist = spec.referenceList
                    for itemlist in [reflist.appendedItems, reflist.explicitItems,
                                     reflist.addedItems,
                                     reflist.prependedItems, reflist.orderedItems]:
                        if itemlist:
                            for reference in itemlist:
                                reference_path = reference.assetPath
                                if reference_path:
                                    # print reference_path
                                    with Ar.ResolverContextBinder(stage.GetPathResolverContext()):
                                        resolver = Ar.GetResolver()
                                        # we resolve the payload path relative to the primSpec layer path (layer.identifier)
                                        # far more likely to be correct. i hope
                                        resolvedpath = resolver.AnchorRelativePath(spec.layer.identifier,
                                                                                   reference_path)
                                        
                                        info = {}
                                        info['online'] = os.path.isfile(resolvedpath)
                                        info['path'] = resolvedpath
                                        info['type'] = 'reference'
                                        
                                        self.nodes[resolvedpath] = info
                                        
                                        if spec.layer.identifier != resolvedpath:
                                            if not [spec.layer.identifier, resolvedpath, 'reference'] in self.edges:
                                                self.edges.append([spec.layer.identifier, resolvedpath, 'reference'])
                
                if spec.variantSets:
                    for varset in spec.variantSets:
                        thisvarset = prim.GetVariantSet(varset.name)
                        current_variant_name = thisvarset.GetVariantSelection()
                        current_variant = varset.variants[current_variant_name]
                        for variant_name in varset.variants.keys():
                            variant = varset.variants[variant_name]
                            
                            # todo: put variant info onto layer
                            
                            # for key in variant.GetMetaDataInfoKeys():
                            #     print key, variant.GetInfo(key)
                            
                            # variants that are linked to payloads
                            # variants can have other mechanisms, but sometimes they're a payload
                            payloads = variant.GetInfo('payload')
                            for itemlist in [payloads.appendedItems, payloads.explicitItems, payloads.addedItems,
                                             payloads.prependedItems, payloads.orderedItems]:
                                for payload in itemlist:
                                    pathToResolve = payload.assetPath
                                    anchorPath = variant.layer.identifier
                                    with Ar.ResolverContextBinder(stage.GetPathResolverContext()):
                                        resolver = Ar.GetResolver()
                                        resolvedpath = resolver.AnchorRelativePath(anchorPath, pathToResolve)
                                        if not [anchorPath, resolvedpath, 'payload'] in self.edges:
                                            self.edges.append([anchorPath, resolvedpath, 'payload'])
                
                # def, over or class
                # print 'GetSpecifier', spec.specifier
                # component,
                # print 'GetKind', spec.kind
                # print '--'
            
            # clips - this seems to be the way to do things
            # clips are not going to be picked up by the stage layers inspection stuff
            # apparently they're expensive. whatever.
            # no prim stack shennanigans for us
            # gotta get a clip on each prim and then test it for paths?
            clips = Usd.ClipsAPI(prim)
            if clips.GetClipAssetPaths():
                # print 'CLIPS'.center(30, '-')
                # dict of clip info. full of everything
                # key is the clip *name*
                clip_dict = clips.GetClips()
                # print clip_dict
                
                """
                @todo: subframe handling
                integer frames: path/basename.###.usd
                subinteger frames: path/basename.##.##.usd.
                
                @todo: non-1 increments
                """
                # don't use resolved path in case either the first or last file is missing from disk
                firstFile = str(clips.GetClipAssetPaths()[0].path)
                lastFile = str(clips.GetClipAssetPaths()[-1].path)
                firstFileNum = digitSearch.findall(firstFile)[-1]
                lastFileNum = digitSearch.findall(lastFile)[-1]
                digitRange = str(firstFileNum + '-' + lastFileNum)
                nodeName = ''
                
                firstFileParts = firstFile.split(firstFileNum)
                for i in range(len(firstFileParts) - 1):
                    nodeName += str(firstFileParts[i])
                
                nodeName += digitRange
                nodeName += firstFileParts[-1]
                
                allFilesFound = True
                for path in clips.GetClipAssetPaths():
                    if (path.resolvedPath == ''):
                        allFilesFound = False
                        break
                
                # TODO : make more efficient - looping over everything currently
                # TODO: validate presence of all files in the clip seq. bg thread?
                
                # GetClipSets seems to be crashing this houdini build - clips.GetClipSets()
                clip_sets = clips.GetClips().keys()
                
                # print 'GetClipManifestAssetPath', clips.GetClipManifestAssetPath().resolvedPath
                # this is a good one - resolved asset paths too
                for clipSet in clip_sets:
                    for path in clips.GetClipAssetPaths(clipSet):
                        # print path, type(path)
                        # print path.resolvedPath
                        pass
                
                # layer that hosts list clip
                # but this is the MANIFEST path
                # not really correct. it'll have to do for now.
                layer = clips.GetClipManifestAssetPath().resolvedPath
                
                if not nodeName in self.nodes:
                    info = {}
                    info['online'] = allFilesFound
                    info['path'] = nodeName
                    info['type'] = 'clip'
                    
                    self.nodes[nodeName] = info
                
                if not [layer, nodeName, 'clip'] in self.edges:
                    self.edges.append([layer, nodeName, 'clip'])
        
        # print 'end test'.center(40, '-')
    
    
    def layerprops(self, layer):
        print 'layer props'.center(40, '-')
        
        for prop in ['anonymous', 'colorConfiguration', 'colorManagementSystem', 'comment', 'customLayerData',
                     'defaultPrim', 'dirty', 'documentation', 'empty', 'endTimeCode', 'expired', 'externalReferences',
                     'fileExtension', 'framePrecision',
                     'framesPerSecond', 'hasOwnedSubLayers', 'identifier', 'owner', 'permissionToEdit',
                     'permissionToSave', 'pseudoRoot', 'realPath', 'repositoryPath', 'rootPrimOrder', 'rootPrims',
                     'sessionOwner', 'startTimeCode', 'subLayerOffsets', 'subLayerPaths', 'timeCodesPerSecond',
                     'version']:
            print prop, getattr(layer, prop)
        print ''.center(40, '-')
        
        defaultprim = layer.defaultPrim
        if defaultprim:
            print defaultprim, type(defaultprim)


def find_node(node_coll, attr_name, attr_value):
    for x in node_coll:
        node = node_coll[x]
        if getattr(node, attr_name) == attr_value:
            return node


@QtCore.Slot(str, object)
def on_nodeMoved(nodeName, nodePos):
    # print('node {0} moved to {1}'.format(nodeName, nodePos))
    pass


class FindNodeWindow(QtWidgets.QDialog):
    def __init__(self, nodz, parent=None):
        self.nodz = nodz
        super(FindNodeWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)
        
        self.build_ui()
    
    
    def search(self):
        search_text = self.searchTxt.text()
        
        self.foundNodeList.clear()
        if search_text == '':
            return
        
        for x in sorted(self.nodz.scene().nodes):
            if fnmatch.fnmatch(x.lower(), '*%s*' % search_text.lower()):
                self.foundNodeList.addItem(QtWidgets.QListWidgetItem(x))
    
    
    def item_selected(self, *args):
        items = self.foundNodeList.selectedItems()
        if items:
            sel = [x.text() for x in items]
            
            for x in self.nodz.scene().nodes:
                node = self.nodz.scene().nodes[x]
                if x in sel:
                    node.setSelected(True)
                else:
                    node.setSelected(False)
            self.nodz._focus()
    
    
    def build_ui(self):
        lay = QtWidgets.QVBoxLayout()
        self.setLayout(lay)
        self.searchTxt = QtWidgets.QLineEdit()
        self.searchTxt.textChanged.connect(self.search)
        lay.addWidget(self.searchTxt)
        
        self.foundNodeList = QtWidgets.QListWidget()
        self.foundNodeList.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.foundNodeList.itemSelectionChanged.connect(self.item_selected)
        lay.addWidget(self.foundNodeList)


class NodeGraphWindow(QtWidgets.QDialog):
    def __init__(self, usdfile=None, parent=None):
        self.usdfile = usdfile
        self.root_node = None
        
        super(NodeGraphWindow, self).__init__(parent)
        self.settings = QtCore.QSettings("chrisg", "usd-dependency-graph")
        
        self.nodz = None
        
        self.find_win = None
        self.build_ui()
        if self.usdfile:
            self.load_file()
    
    
    def build_ui(self):
        
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        else:
            self.resize(600, 400)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMinimizeButtonHint);
        lay = QtWidgets.QVBoxLayout()
        self.setLayout(lay)
        
        self.toolbar_lay = QtWidgets.QHBoxLayout()
        lay.addLayout(self.toolbar_lay)
        
        self.openBtn = QtWidgets.QPushButton("Open...", )
        self.openBtn.setShortcut('Ctrl+o')
        self.openBtn.clicked.connect(self.manualOpen)
        self.toolbar_lay.addWidget(self.openBtn)
        
        self.reloadBtn = QtWidgets.QPushButton("Reload")
        self.reloadBtn.setShortcut('Ctrl+r')
        self.reloadBtn.clicked.connect(self.load_file)
        self.toolbar_lay.addWidget(self.reloadBtn)
        
        self.findBtn = QtWidgets.QPushButton("Find...")
        self.findBtn.setShortcut('Ctrl+f')
        self.findBtn.clicked.connect(self.findWindow)
        self.toolbar_lay.addWidget(self.findBtn)
        
        self.layoutBtn = QtWidgets.QPushButton("Layout Nodes")
        self.layoutBtn.clicked.connect(self.layout_nodes)
        self.toolbar_lay.addWidget(self.layoutBtn)
        
        toolbarspacer = QtWidgets.QSpacerItem(10, 10, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.toolbar_lay.addItem(toolbarspacer)
        
        logger.info('building nodes')
        configPath = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'nodz_config.json')
        
        self.nodz = nodz_main.Nodz(None, configPath=configPath)
        self.nodz.editLevel = 1
        # self.nodz.editEnabled = False
        lay.addWidget(self.nodz)
        self.nodz.initialize()
        self.nodz.signal_NodeMoved.connect(on_nodeMoved)
        self.nodz.signal_NodeContextMenuEvent.connect(self.node_context_menu)
    
    
    def findWindow(self):
        if self.find_win:
            self.find_win.close()
        
        self.find_win = FindNodeWindow(self.nodz, parent=self)
        self.find_win.show()
        self.find_win.activateWindow()
    
    
    def get_node_from_name(self, node_name):
        return self.nodz.scene().nodes[node_name]
    
    
    def node_path(self, node_name):
        node = self.get_node_from_name(node_name)
        userdata = node.userData
        print userdata.get('path')
    
    
    def view_usdfile(self, node_name):
        node = self.get_node_from_name(node_name)
        userdata = node.userData
        path = userdata.get('path')
        if path.endswith(".usda"):
            win = text_view.TextViewer(path, parent=self)
            win.show()
        else:
            print 'can only view usd ascii files'
    
    
    def node_context_menu(self, event, node):
        menu = QtWidgets.QMenu()
        menu.addAction("print path", partial(self.node_path, node))
        menu.addAction("View USD file...", partial(self.view_usdfile, node))
        
        menu.exec_(event.globalPos())
    
    
    def load_file(self):
        
        if not os.path.isfile(self.usdfile):
            raise RuntimeError("Cannot find file: %s" % self.usdfile)
        
        self.nodz.clearGraph()
        self.root_node = None
        self.setWindowTitle(self.usdfile)
        
        x = DependencyWalker(self.usdfile)
        x.start()
        
        nodz_scene = self.nodz.scene()
        rect = nodz_scene.sceneRect()
        center = [rect.center().x(), rect.center().y()]
        
        # pprint(x.nodes)
        nds = []
        for i, node in enumerate(x.nodes):
            
            info = x.nodes[node]
            # print node
            rnd = random.seed(i)
            
            pos = QtCore.QPointF((random.random() - 0.5) * 1000 + center[0],
                                 (random.random() - 0.5) * 1000 + center[1])
            node_label = os.path.basename(node)
            
            # node colouring / etc based on the node type
            node_preset = 'node_default'
            if info.get("type") == 'clip':
                node_preset = 'node_clip'
            elif info.get("type") == 'payload':
                node_preset = 'node_payload'
            elif info.get("type") == 'variant':
                node_preset = 'node_variant'
            elif info.get("type") == 'specialize':
                node_preset = 'node_specialize'
            elif info.get("type") == 'reference':
                node_preset = 'node_reference'
            if not node_label in nds:
                nodeA = self.nodz.createNode(name=node_label, preset=node_preset, position=pos)
                if self.usdfile == node:
                    self.root_node = nodeA
                
                if nodeA:
                    self.nodz.createAttribute(node=nodeA, name='out', index=0, preset='attr_preset_1',
                                              plug=True, socket=False, dataType=int, socketMaxConnections=-1)
                    
                    nodeA.userData = info
                    
                    if info['online'] is False:
                        self.nodz.createAttribute(node=nodeA, name='OFFLINE', index=0, preset='attr_preset_2',
                                                  plug=False, socket=False)
                
                nds.append(node_label)
        
        # pprint(x.edges)
        
        # print 'wiring nodes'.center(40, '-')
        # create all the node connections
        for edge in x.edges:
            start = os.path.basename(edge[0])
            end = os.path.basename(edge[1])
            port_type = edge[2]
            start_node = self.nodz.scene().nodes[start]
            end_node = self.nodz.scene().nodes[end]
            self.nodz.createAttribute(node=start_node, name=port_type, index=-1, preset='attr_preset_1',
                                      plug=False, socket=True, dataType=int, socketMaxConnections=-1)
            
            self.nodz.createConnection(end, 'out', start, port_type)
        
        # any nodes that don't have output connections
        # ie, loose nodes
        # use the layer traversal connections
        for node_name in self.nodz.scene().nodes:
            node = self.nodz.scene().nodes[node_name]
            if not node.plugs['out'].connections:
                if node == self.root_node:
                    # skip the root node - it's never gonna have an out connection
                    continue
                
                node_path = node.userData.get("path")
                edge_info = [f for f in x.init_edges if f[1] == node_path]
                if edge_info:
                    start = os.path.basename(edge_info[0][1])
                    end = os.path.basename(edge_info[0][0])
                    end_node = self.nodz.scene().nodes[end]
                    
                    self.nodz.createAttribute(node=end_node, name='sublayer', index=-1, preset='attr_preset_1',
                                              plug=False, socket=True, dataType=int, socketMaxConnections=-1)
                    
                    self.nodz.createConnection(start, 'out', end, 'sublayer')
        
        # layout nodes!
        self.nodz.arrangeGraph(self.root_node)
        # self.nodz.autoLayoutGraph()
        self.nodz._focus()
    
    
    def layout_nodes(self):
        # layout nodes!
        self.nodz.arrangeGraph(self.root_node)
        
        self.nodz._focus(all=True)
    
    
    def manualOpen(self):
        """
        Manual open method for manually opening the manually opened files.
        """
        startPath = None
        if self.usdfile:
            startPath = os.path.dirname(self.usdfile)
        
        multipleFilters = "USD Files (*.usd *.usda *.usdc) (*.usd *.usda *.usdc);;All Files (*.*) (*.*)"
        filename = QtWidgets.QFileDialog.getOpenFileName(
            QtWidgets.QApplication.activeWindow(), 'Open File', startPath or '/', multipleFilters,
            None, QtWidgets.QFileDialog.DontUseNativeDialog)
        if filename[0]:
            print filename[0]
            self.usdfile = filename[0]
            self.load_file()
    
    
    def closeEvent(self, *args, **kwargs):
        """
        Window close event. Saves preferences. Impregnates your dog.
        """
        if self.find_win:
            self.find_win.close()
        
        self.settings.setValue("geometry", self.saveGeometry())
        super(NodeGraphWindow, self).closeEvent(*args)


def main(usdfile=None):
    # usdfile = utils.sanitize_path(usdfile)
    # usdfile = usdfile.encode('unicode_escape')
    
    par = QtWidgets.QApplication.activeWindow()
    win = NodeGraphWindow(usdfile=usdfile, parent=par)
    win.show()
