#/usr/bin/env python

import luna
import tornado.ioloop
import tornado.web
import tornado.httpserver
import tornado.gen
import threading
import datetime
import time
from bson.dbref import DBRef
from luna.utils import set_mac_node

last_switch_update = None
lock_last_switch_update = threading.Lock()
switch_table_updater_running = False
lock_switch_table_updater_running = threading.Lock()
switch_mac_table = None
lock_switch_mac_table = threading.Lock()


class Manager(tornado.web.RequestHandler):

    def initialize(self, params):
        self.server_ip = params['server_ip']
        self.server_port = params['server_port']
        self.mongo = params['mongo_db']
        self.app_logger = params['app_logger']

    @tornado.web.asynchronous
    @tornado.gen.engine
    def get(self):
        step = self.get_argument('step')
        if step == 'boot':
            nodes = luna.list('node')
            self.render("templ_ipxe.cfg", server_ip = self.server_ip, server_port = self.server_port, nodes = nodes)
        if step == 'discovery':
            try:
                hwdata = self.get_argument('hwdata')
            except:
                hwdata = None
            if not bool(hwdata):
                self.send_error(400) #  Bad Request
                return
            try:
                req_nodename = self.get_argument('node')
            except:
                req_nodename = None
            macs = set(hwdata.split('|'))
            # enter node name manualy from ipxe
            if req_nodename:
                try:
                    node = luna.Node(name = req_nodename, mongo_db = self.mongo['node'])
                except:
                    self.app_logger.error("No such node configured in DB. '{}'".format(req_nodename))
                    self.send_error(400)
                    return
                mac = None
                for i in range(len(macs)):
                    if bool(macs[i]):
                        mac = macs[i]
                        break
                if mac:
                    mac = mac.lower()
                    set_mac_node(mac, node.DBRef)
                else:
                    self.send_error(400) #  Bad Request
                    return
            # need to find node fo given macs.
            # first step - trying to find in know macs
            found_node_dbref = None
            for mac in macs:
                if not bool(mac):
                    continue
                mac = mac.lower()
                try:
                    found_node_dbref = self.mongo['mac'].find_one({'mac': mac}, {'_id': 0, 'node': 1})['node']
                except:
                    #self.app_logger.error("Mac record exists, but no node configured for given mac '{}'".format(mac))
                    #self.send_error(404)
                    #return
                    continue
                if bool(found_node_dbref):
                    break

            # second step. now try to find in learned switch macs if we have switch/port configured
            if not bool(found_node_dbref):
                mac_from_cache = None
                for mac in macs:
                    mac_cursor = self.mongo['switch_mac'].find({'mac': mac})
                    for elem in mac_cursor:
                        switch_id = elem['switch_id']
                        port = elem['port']
                        try:
                            found_name_from_learned = self.mongo['node'].find_one({'switch': DBRef('switch', switch_id), 'port': port}, {})['name']
                            mac_from_cache = mac
                        except:
                            found_name_from_learned = None
                            mac_from_cache = None
                        if mac_from_cache:
                            break
                    if mac_from_cache:
                        break
                if not bool(mac_from_cache):
                    self.app_logger.info("Cannot find '{}' in learned macs.".format(macs))
                    # did not find in learned macs
                    self.send_error(404)
                    return
                # here we should have found_name_from_learned and mac_from_cache
                try:
                    node = luna.Node(name = found_name_from_learned, mongo_db = self.mongo)
                    set_mac_node(mac_from_cache, node.DBRef)
                    found_node_dbref = node.DBRef
                except:
                    # should not be here
                    self.app_logger.info("Cannot create node object for '{}' and '{}'".format(found_name_from_learned, self.mongo))
                    self.send_error(404)
                    return
            # here we should have found_node_dbref
            try:
                node = luna.Node(id = found_node_dbref.id, mongo_db = self.mongo)
            except:
                # should not be here
                self.app_logger.info("Cannot create node object for '{}' and '{}'".format(found_node_dbref, self.mongo))
                self.send_error(404)
                return
            # found node finally
            #http_path = "http://" + self.server_ip + ":" + str(self.server_port) + "/boot/"
            boot_params = node.boot_params
            if not boot_params['boot_if']:
                boot_params['ifcfg'] = 'dhcp'
            else:
                boot_params['ifcfg'] = boot_params['boot_if'] + ":" + boot_params['ip'] + "/" + str(boot_params['net_prefix'])
            boot_params['delay'] = 10
            self.render("templ_nodeboot.cfg",
                    params = boot_params, server_ip = self.server_ip,
                    server_port = self.server_port, nodename = node.name)
        if step == 'install':
            try:
                node_name = self.get_argument('node')
            except:
                self.app_logger.error("No nodename for install step specified.")
                #return self.send_error(400)
                self.send_error(400)
                return
            try:
                node = luna.Node(name = node_name, mongo_db = self.mongo)
            except:
                self.app_logger.error("No such node for install step found '{}'.".format(node_name))
                #return self.send_error(400)
                self.send_error(400)
                return
                #self.finish()
            install_params = node.install_params
            if not bool(install_params['torrent']):
                #return self.send_error(404)
                self.send_error(404)
                return
                #self.finish()
            self.render("templ_install.cfg", p = install_params, server_ip = self.server_ip, server_port = self.server_port,)