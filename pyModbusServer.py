#!/usr/bin/python
#
# Configurable modbus server for test purposes
#
# Supported ranges:
# 1-9999 - discrete output coils R/W - binary
# 10001 - 19999 - discrete input contacts R/O - binary
# 30001 - 39999 - analog input registers - R/O - 16 bit int
# 40001 - 49999 - analog output holding registers - R/W - 16 bit int
#
# dependencies: numpy, pymodbustcp

import logging
import time
import random
import configparser
from pyModbusTCP.server import ModbusServer
import numpy as np


#read config file
config = configparser.ConfigParser()
config.read("config.txt")

# setup logging
logger = logging.getLogger(__name__)
logger.setLevel( config.get("system", "loglevel") )
logging.basicConfig(filename=config.get("system", "logfile"), 
                    format="{asctime} - {levelname} - {name} - {message}", style="{" )
logger.info('pyModbusServer Startup')
# add in some logs from the pyModbus class (logs connecting IPs)
mbs_log = logging.getLogger("pyModbusTCP.server")
mbs_log.setLevel("DEBUG")


mb_server = ModbusServer(host=config.get("system", "listen_address"), 
                         port=int(config.get("system", "listen_port")), 
                         no_block=True)


# load register and coil info from config file
changing_registers = dict()
changing_coils = dict()

for register_address in dict(config.items('registers')):
    #input "rand,$min,$max,$period" or "risefall,$min,$max,$period" or just a number
    val = config.get("registers", register_address).split(",")    
    logger.debug("CONFIG READ: register_address: " + str(register_address) +" val: " + str(val ) )
    register_address = int(register_address)

    if val[0][0] == "r": # is either rand or risefall, so add to dynamic values
        
        #output rand,$min,$max,$period, $value, $lastchange" or "risefall,$min,$max,$period, $value, $lastchange"
        changing_registers[register_address] = (val[0], int(val[1]), int(val[2]), float(val[3]), 0, 0)
        logger.info("setting changing: " + str(register_address) + " to: " + str(changing_registers[register_address]))                

        list = []
        list.insert( register_address ,  0 ) 
        mb_server.data_hdl.write_h_regs(register_address, list, None)

    else:

        #not a changing value, just set it to the value in the config file
        logger.info("setting fixed register: " + str(register_address) + " to: " + str(val))            
        list = []        
        list.insert( register_address ,  int(val[0]) ) 
        mb_server.data_hdl.write_h_regs(register_address, list, None)


for coil_address in dict(config.items('coils')): # work through all coils specified in config file
    val = config.get("coils", coil_address)
    logger.debug("CONFIG: coil_address: " + str(coil_address) +" val: " + str(val ) )
    coil_address = int(coil_address)

    #input from config 0, 1, rand,$period or toggle,$period
    #output to dict [<type>, <period (S)>, <value>, <lastchange>]
    if val[0] == "r" or val[0] == "t": # rand or toggle
        writeval = random.randint(0,1)
        period = float(val.split(",")[1])
        changing_coils[coil_address] = ("rand",period, writeval, 0)     
        logger.info("setting changing coil: " + str(coil_address) + " to: " + str(changing_coils[coil_address]))                              
    else: # 1 or 0 so just set it
        writeval = val
        logger.info("setting fixed coil : " + str(coil_address) + " to: " + str(val))     
      
    list = [writeval]
    mb_server.data_hdl.write_coils(coil_address, list, "None")
    

#start modbus server
mb_server.start()
if (not mb_server._evt_running.is_set()):
    logger.error("Failed to start Modbus Server")
    exit(0)


#main loop, iterate over items in the changing_registers and changing_coils
last_time = start_time = time.time()
i = total_time = 0

while 1:
    i=i+1
    now = time.time()
    gap = now - last_time
    total_time = now - start_time

    for key, value in changing_registers.items():
         #output rand,$min,$max,$period, $value, $lastchange" or "risefall,$min,$max,$period, $value, $lastchange"
        
        if (now - value[5]) > value[3]: # if time since last change is greater than the period, the value needs updating
            # type of change is in value[0] and for changing ones can be: rand(range) or risefall(range, period in s)
            if value[0][0] == "r":
                min = value[1]
                max = value[2]
                period = value[3]

                if value[0][1] == "a": #rand(x)
                    
                    new_value = random.randint(min,max)                    

                else: #risefall                                        

                    # y = Amplitude * sin(  (2pi/period) * (x)) + vertical-shift
                    # amplitude = 0.5*max value, vertical shift = max - 0.5range
                    # format: risefall(0,10000,60)', period (always 0.1), value, lastchange
                    range = max - min
                    period_val = (2 * np.pi / period) * total_time
                    new_value = int ( 
                        (0.5 * range * np.sin(period_val))  +  (int(max) - (0.5 * range)) 
                        )
                    logger.debug("val: " +value[0] + " rt " + str(total_time) + " minx: " + str(min) + " max " + str(max) + " range " + str(range) + " per " + str(period) + " newval " + str(new_value))

            logger.debug("Changing register: " + str(key) + " from " + str(value[2]) + " to " + str(new_value))
            #rand,$min,$max,$period, $value, $lastchange
            changing_registers.update({key : [value[0], value[1], value[2], value[3], new_value, now]}) #update the dict
            # now change the item in the modbus server
            list = []
            list.insert( key ,  new_value ) 
            mb_server.data_hdl.write_h_regs(key, list, None)


    for key, value in changing_coils.items():
        #format is address: [<type>, <period>, <value>, <lastchange>]
        
        if (now - value[3]) > value[1]: # if time since last change is greater than the period, the value needs updating                        
            if value[0][0] == "r": # rand
                new_value = random.randint(0,1)       
            else: #toggle
                new_value = int(value[2])
                new_value ^= 1

            logger.debug("Changing coil: " + str(key) + " from " + str(value[2]) + " to " + str(new_value))
            changing_coils.update({key : [value[0], value[1], new_value, now]}) #update the dict
            # now change the item in the modbus server
            list = [new_value]
            res = mb_server.data_hdl.write_coils(key, list, "None")
  
            
    last_time = now
    time.sleep(0.05)

