import os
import argparse
import math
import queue
cycle=0
class Config(object):
    def __init__(self, iodir):
        self.filepath = os.path.abspath(os.path.join(iodir, "Config_richHardware.txt"))
        self.parameters = {} # dictionary of parameter name: value as strings.

        try:
            with open(self.filepath, 'r') as conf:
                self.parameters = {line.split('=')[0].strip(): line.split('=')[1].split('#')[0].strip() for line in conf.readlines() if not (line.startswith('#') or line.strip() == '')}
            print("Config - Parameters loaded from file:", self.filepath)
            print("Config parameters:", self.parameters)
        except:
            print("Config - ERROR: Couldn't open file in path:", self.filepath)
            raise
class IMEM(object):
    def __init__(self, iodir):
        self.size = pow(2, 16) # Can hold a maximum of 2^16 instructions.
        self.filepath = os.path.abspath(os.path.join(iodir, "Code_lowLevel.asm"))
        self.instructions = []

        try:
            with open(self.filepath, 'r') as insf:
                self.instructions = [ins.split('#')[0].strip() for ins in insf.readlines() if not (ins.startswith('#') or ins.strip() == '')]
            print("IMEM - Instructions loaded from file:", self.filepath)
            # print("IMEM - Instructions:", self.instructions)
        except:
            print("IMEM - ERROR: Couldn't open file in path:", self.filepath)
            raise

    def Read(self, idx): # Use this to read from IMEM.
        if idx < self.size:
            return self.instructions[idx]
        else:
            print("IMEM - ERROR: Invalid memory access at index: ", idx, " with memory size: ", self.size)
class DispatchQueue(object):
    def __init__(self,config) :
        self.VectorQueueSize=int(config.parameters.get("computeQueueDepth"))
        self.DataQueueSize=int(config.parameters.get("dataQueueDepth"))
        self.VectorQueue=queue.Queue(self.VectorQueueSize)
        self.DataQueue=queue.Queue(self.DataQueueSize)
    #How to take care of stall( queue is full, no instruction cuold come in), just calculate this lines maxmium available cycles, and update the cycle
    #So this instruction is done, can pop in a new instruction
    def runVector(self):
        global cycle
        if self.VectorQueue.qsize()>4:
            nextCycle=self.VectorQueue.poll()
            cycle=math.max(cycle,nextCycle)
        #the cycle is based on the last instruction
        if self.VectorQueue.qsize()==0:
            cycleLast=cycle
        else:
            cycleLast = max(cycle,self.VectorQueue.get(self.VectorQueue.qsize()-1))   
        #return last cycle and send it to computation union
        return cycleLast
    def pushRunVector(self,newcycle):
        #update the available cycle for the destination register
        #push the cycle for the section in to the queue
        self.VectorQueue.put(newcycle)
    def runData(self,nextAvailableCycle):
        #the first if is the first possible free space to pop in a cycle
        global cycle
        if self.DataQueue.qsize()>=4:
            nextCycle=self.DataQueue.get()
            cycle=max(cycle,nextCycle)
        self.DataQueue.put(nextAvailableCycle)
    def emptyQueue(self):
        global cycle
        while self.VectorQueue.qsize()>0:
            cycle=max(cycle,self.VectorQueue.get())
        while self.DataQueue.qsize()>0:
            cycle=max(cycle,self.DataQueue.get())
class ComputeQueue(object):#more like compute union
    def __init__(self,config):
        #an array for the instruction waiting and it has a maxinum depth
        self.numLine=int(config.parameters.get("numLanes"))
        self.mul=int(config.parameters.get("pipelineDepthMul"))
        self.div=int(config.parameters.get("pipelineDepthDiv"))
        self.add=int(config.parameters.get("pipelineDepthAdd"))
        self.mulC=0
        self.addC=0
        self.divC=0
    def change(self,mod,lastCycle):
        #change the compution pipeline, and return the end pipe
        #next for this step is call the busy board to change the available cycle
        if mod==1:
            self.addC=lastCycle+math.ceil(64/self.numLine)+self.add-1
            return self.addC
        elif mod==2:
            self.divC=lastCycle+math.ceil(64/self.numLine)-1+self.div
            return self.divC
        else:
            self.mulC=lastCycle+math.ceil(64/self.numLine)-1+self.mul
            return self.mulC 
class MemoryBusyBoard(object):
    #cause the scalar value and read is 1 cycle so, we need to use a busy board to trace what happen in the scalar memory
    def __init__(self,config):
        self.numBank=int(config.parameters.get("vdmNumBanks"))
        self.depth=int(config.parameters.get("vlsPipelineDepth"))
        self.bank=[0x0 for i in range(int(self.numBank))]
    def change(self,add,strid,offset):
        #change the board of available cycle
        #return the available cycle for the register
        cycleNeed = 0
        #set the bank to the perioud time
        

        #example for add and offset
        add=1

        for i in range(self.numBank):
            self.bank[i]=max(cycle,self.bank[i])
        bankChange=[False for i in range(self.numBank)]
        for i in range(64):
            choosedBank=(add+offset[i]+strid*i)%self.numBank
            self.bank[choosedBank]+=1
            bankChange[choosedBank]=True
        for i in range(self.numBank):
            if(bankChange[i]):
                self.bank[i]=self.bank[i]+self.depth-1
                cycleNeed=max(cycleNeed,self.bank[i])
                #if the bank is used, the max cycleNeed should count him
        return cycleNeed    
class BusyBoard(object):
    def __init__(self):
        self.Register={}
    def check(self,register):
        #return the register available cycle
        return self.Register.get(register,0x0)
    def change(self,register,newcycle):
        self.Register[register]=newcycle
class Core():
    def __init__(self, imem, dq, cq,bb,mb):
        self.IMEM = imem
        self.DQ = dq
        self.CQ = cq
        self.BB=bb
        self.MBB=mb
        self.idx=0     
    def run(self):
        global cycle
        self.idx=0
        while(self.idx<len(self.IMEM.instructions)):
            global cycle
            inst = self.IMEM.Read(self.idx)
            self.idx+=1
            #print(inst)
            para =inst.split()
            if len(para)<3:
                continue
            register=para[1]#type string
            #check the busy board            
            if len(para)==4:
                cycle=max(cycle,self.BB.check(para[3]))
            cycle=max(cycle,self.BB.check(para[2]))
            cycle=max(cycle,self.BB.check(para[1]))
            #send it to the dispatch queue
            mod=0
            addr=para[2]
            if para[0]=='ADD':
                mod=1
            elif para[0]=='DIV':
                mod=2
            elif para[0]=='MUL':
                mod=3           
            elif para[0]=='LV' or para[0]=='SV':
                mod=-1
                strid=1
                offset=[0 for i in range(64)]
            elif para[0]=='SVWS'or para[0]=='LVWS':
                mod=-1
                #strid=para[3]
                offset=[0 for i in range(64)]
                strid=2
            elif para[0]=='LVI'or para[0]=='SVI':
                mod=-1
                strid=1
                #offset=para[3]
                offset=[0x16*i for i in range(64)]
                strid=2
            # only two kind of instruction is more than 1 cycle
            if mod>0:
                self.vector(mod,register)
            elif mod==-1:
                self.data(addr,strid,offset)
            cycle+=1

    def vector(self,mod,register):
        global cycle
        cycle+=1
        lastCycle=self.DQ.runVector()
        cycleForBusy=self.CQ.change(mod,lastCycle)
        self.DQ.pushRunVector(cycleForBusy)
        #update the busy board
        self.BB.change(register,cycleForBusy)
    def data(self,addr,strid,offset):
        global cycle
        cycle+=1
        cycleForBusy=self.MBB.change(addr,strid,offset)
        self.DQ.runData(cycleForBusy)
    def empty(self):
        global cycle
        #empty the busy board and empty the queue
        self.DQ.emptyQueue()
        cycle=max(cycle,self.CQ.mulC)
        cycle=max(cycle,self.CQ.addC)
        cycle=max(cycle,self.CQ.addC)
if __name__ == "__main__":
    #parse arguments for input file location
    parser = argparse.ArgumentParser(description='Vector Core Functional Simulator')
    parser.add_argument('--iodir', default="", type=str, help='Path to the folder containing the input files - instructions and data.')
    args = parser.parse_args()

    iodir = os.path.abspath(args.iodir)
    print("IO Directory:", iodir)

    # Parse Config
    config = Config(iodir)

    # Parse IMEM
    imem = IMEM(iodir)  

    #inital dispatch queue
    dq=DispatchQueue(config)

    #inital compute queue
    cq=ComputeQueue(config)
    #inital busyBorad
    bb=BusyBoard()

    #inital busyBorad
    mb=MemoryBusyBoard(config)


    # Create Vector Core
    vcore = Core(imem, dq, cq, bb,mb)

    # Run Core
    for i in range(256):
        vcore.run()
    vcore.empty()
    print(cycle)
    # THE END