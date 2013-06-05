#!/usr/bin/env python
#
# run_tests.py -- Run regression tests
#
# Author: Mark Liffiton
# Date: October 2012
#

import json
import math
import os
import sys
import subprocess
import time
from collections import defaultdict
from multiprocessing import Process, Queue, JoinableQueue, cpu_count

# pull in configuration from testconfig.py
import testconfig

# globals (w/ default values)
mode = 'runp'
verbose = False

# Build all tests to be run
def makeTests(testexe):
    # Gather commands
    cmds = []
    for exe in testconfig.exes:
        if testexe and exe['name'] != testexe:
            continue

        cmd = exe['cmd']

        if not os.access(cmd, os.X_OK):
            print "ERROR: %s is not an executable file.  Do you need to run make?" % cmd
            sys.exit(1)

        flags = exe.get('flags', [''])
        exclude = exe.get('exclude', [])

        for flag in flags:
            cmds.append([ [cmd] + flag.split() , exclude ])

    jobs = []
    testid = 0  # unique id for each test
    for (cmd, exclude) in cmds:
        for testfile in testconfig.files:
            infile = testfile[0]

            if infile in exclude:
                continue

            if len(testfile) > 1:
                outfile = testfile[1]
            else:
                outfile = infile + ".out"

            outfile = "out/" + outfile
            errfile = "out/" + infile + ".err"

            jobs.append( [ testid , cmd + [infile] , outfile , errfile ] )
            testid += 1

    return jobs

def runTests(jobq, msgq, pid):
    while not jobq.empty():
        testid, cmd, outfile, errfile = jobq.get()
        msgq.put((testid,'start',None))
        result, runtime = runTest(cmd, outfile, errfile, pid)
        msgq.put((testid,result,runtime))
        jobq.task_done()
    msgq.put((None,'done',None))

# pid is so different processes don't overwrite each other's tmp files
def runTest(cmd, outfile, errfile, pid):
    global mode, verbose

    if mode == "nocheck":
        tmpout = os.devnull
        tmperr = os.devnull
    elif mode == "regenerate":
        tmpout = outfile
        tmperr = os.devnull
    else:
        tmpout = outfile + ".NEW" + str(pid)
        tmperr = errfile + str(pid)

    if verbose:
        print "\n[34;1mRunning test:[0m %s > %s 2> %s" % (" ".join(cmd), tmpout, tmperr)

    # TODO: handle stderr
    with open(tmpout, 'w') as f_out, open(tmperr, 'w') as f_err:
        try:
            start_time = time.time()
            ret = subprocess.call(cmd, stdout = f_out, stderr = f_err)
            runtime = time.time() - start_time
        except KeyboardInterrupt:
            os.unlink(tmpout)
            os.unlink(tmperr)
            return 'interrupted', None   # not perfect, but seems to deal with CTL-C most of the time

    if ret > 128:
        return 'fail', runtime

    if mode == "nocheck" or mode == "regenerate":
        return None, runtime

    result = checkFiles(outfile, tmpout)

    if verbose:
        if result == 'pass':
            errsize = os.path.getsize(tmperr)
            if errsize:
                print "  [32mTest passed (with output to stderr).[0m"
                result = 'stderr'
            else:
                print "  [32mTest passed.[0m"
        elif result == 'sortsame':
            print "  [33mOutputs not equivalent, but sort to same contents.[0m"
        else:
            print "\n  [37;41mTest failed:[0m %s" % " ".join(cmd)
            errsize = os.path.getsize(tmperr)
            if errsize:
                print "  [31mStderr output:[0m"
                with open(tmperr, 'r') as f:
                    for line in f:
                        print "    " + line,
            # TODO: viewdiff
            # TODO: updateout

    os.unlink(tmpout)
    os.unlink(tmperr)
    return result, runtime

def checkFiles(file1, file2):
    global verbose

    with open(file1) as f1:
        data1 = f1.read()
    with open(file2) as f2:
        data2 = f2.read()

    if len(data1) != len(data2):
        if verbose:
            print "\n  [31mOutputs differ (size).[0m"
        return 'diffsize'

    if data1 != data2:
        # test sorted lines
        sort1 = data1.split('\n').sort()
        sort2 = data2.split('\n').sort()
        if sort1 != sort2:
            if verbose:
                print "\n  [31mOutputs differ (contents).[0m"
            return 'diffcontent'
        else:
            # outputs not equivalent, but sort to same contents
            return 'sortsame'
    
    # everything checks out
    return 'pass'

class Progress:
    # indicator characters
    chr_Pass="[32m*[0m"
    chr_Sort="[33m^[0m"
    chr_StdErr="[34mo[0m"
    chr_Fail="[37;41mx[0m"

    def __init__(self, numTests, do_print):
        # maintain test stats
        self.stats = {
            'total': 0,
            'passed': 0,
            'sortsame': 0,
            'stderr': 0,
            'fail': 0,
        }

        self.do_print = do_print

        if self.do_print:
            # get size of terminal (thanks: stackoverflow.com/questions/566746/)
            self.rows, self.cols = os.popen('stty size', 'r').read().split()
            self.cols = int(self.cols)

            # figure size of printed area
            self.printrows = int(math.ceil(float(numTests) / (self.cols-2)))

            # move forward for blank lines to hold progress bars
            for i in range(self.printrows + 1):
                print
            # print '.' for every test to be run
            for i in range(numTests):
                x = i % (self.cols-2) + 2
                y = i / (self.cols-2)
                self.print_at(x, self.printrows-y, '.')

    def update(self, testid, result):
        # print correct mark, update stats
        if result == 'start':
            c = ':'
            self.stats['total'] += 1
        elif result == 'pass':
            c = self.chr_Pass
            self.stats['passed'] += 1
        elif result == 'sortsame':
            c = self.chr_Sort
            self.stats['passed'] += 1
            self.stats['sortsame'] += 1
        elif result == 'stderr':
            c = self.chr_StdErr
            self.stats['stderr'] += 1
        else:
            c = self.chr_Fail
            self.stats['fail'] += 1

        if self.do_print:
            x = testid % (self.cols-2) + 2
            y = testid / (self.cols-2)
            self.print_at(x, self.printrows-y, c)

    def printstats(self):
        print
        print " %s : %2d / %2d  Passed" % \
                (self.chr_Pass, self.stats['passed'], self.stats['total'])
        if self.stats['sortsame'] > 0:
            print " %s : %2d       Different order, same contents" % \
                    (self.chr_Sort, self.stats['sortsame'])
        if self.stats['stderr'] > 0:
            print " %s : %2d       Produced output to STDERR" % \
                    (self.chr_StdErr, self.stats['stderr'])
        if self.stats['fail'] > 0:
            print " %s : %2d       Failed" % \
                    (self.chr_Fail, self.stats['fail'])
            if not self.do_print:
                print "     Re-run in 'runverbose' mode to see failure details."

    # x is 1-based
    # y is 0-based, with 0 = lowest row, 1 above that, etc.
    def print_at(self, x,y, string):
        # move to correct position
        sys.stdout.write("[%dF" % y)  # y (moves to start of row)
        sys.stdout.write("[%dG" % x)         # x

        sys.stdout.write(string)

        # move back down
        sys.stdout.write("[%dE" % y)

        # move cursor to side and flush anything pending
        sys.stdout.write("[999G")
        sys.stdout.flush()

class TimeData:
    def __init__(self, filename="runtimes.json"):
        self.filename = filename
        try:
            with open(self.filename, 'r') as f:
                data = f.read()
            self.times = defaultdict(int, json.loads(data))
            #for x in sorted(self.times, key=lambda x: self.times[x]):
            #    print self.times[x], x
        except:
            print "No timing data found.  Timing data will be regenerated."
            self.times = defaultdict(int)

    def sort_by_time(self, jobs):
        return sorted(jobs, key = lambda x: self.times[" ".join(x[1])])

    def get_time(self, cmdarray):
        return self.times[" ".join(cmdarray)]

    def store_time(self, cmdarray, runtime):
        self.times[" ".join(cmdarray)] = runtime

    def save_data(self):
        with open(self.filename, 'w') as f:
            f.write(json.dumps(self.times))

def main():
    global mode, verbose

    if len(sys.argv) >= 2:
        mode = sys.argv[1]

    if len(sys.argv) >= 3:
        testexe = sys.argv[2]
    else:
        testexe = None

    validmodes = ['run','runp','runverbose','nocheck','regenerate']

    if mode not in validmodes:
        print "Invalid mode: %s" % mode
        print "Options:", (", ".join(validmode))
        return 1

    if mode =='runverbose':
        verbose = True
        mode = 'run'
    elif mode == 'regenerate':
        sure = raw_input("Are you sure you want to regenerate all test outputs (y/n)? ")
        if sure.lower() != 'y':
            print "Exiting."
            return 1

    if mode == "runp":
        # run tests in parallel
        num_procs = cpu_count()
    else:
        # run, nocheck, and regenerate are done serially.
        #  (nocheck is best for timing, and regenerate
        #  can have issues with output file clashes.)
        num_procs = 1

    # say what we are about to do
    report = "Running all tests"
    if testexe:
        report += " for " + testexe
    if mode == 'nocheck':
        report += " (skipping results checks)"
    if mode == 'regenerate':
        report += " (to regenerate output files)"
    report += "."
    print report

    # build the tests
    jobs = makeTests(testexe)
    numTests = len(jobs)

    # run the tests
    # sort by times, if we have them
    td = TimeData()
    jobq = JoinableQueue()
    for job in td.sort_by_time(jobs):
        jobq.put(job)
    msgq = Queue()
    for pid in range(num_procs):
        p = Process(target=runTests, args=(jobq,msgq,pid,))
        p.daemon = True
        p.start()

    # wait for completion, printing progress/stats as needed
    try:
        prog = Progress(numTests, do_print = (not verbose))
                                  # if verbose is on, printing the progress bar is not needed/wanted
        procs_done = 0
        while procs_done < num_procs:
            testid, result, runtime = msgq.get()
            if result == 'done':
                procs_done += 1
            else:
                if runtime: td.store_time(jobs[testid][1], runtime)
                prog.update(testid, result)

        jobq.join()
        if mode == "run" or mode == "runp":
            prog.printstats()

    except KeyboardInterrupt:
        pass

    td.save_data()

if __name__=='__main__':
    main()

