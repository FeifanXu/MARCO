try:
    import queue
except ImportError:
    import Queue as queue


class MarcoPolo:
    def __init__(self, csolver, msolver, stats, config):
        self.subs = csolver
        self.map = msolver
        self.seeds = SeedManager(msolver, stats, config)
        self.stats = stats
        self.config = config
        self.aim_high = self.config['aim'] == 'MUSes'  # used frequently
        self.n = self.map.n   # number of constraints
        self.got_top = False  # track whether we've explored the complete set (top of the lattice)
        self.singleton_MCSes = set()  # store singleton MCSes to pass as hard clauses to shrink()

    def enumerate_basic(self):
        '''Basic MUS/MCS enumeration, as a simple example.'''
        while True:
            seed = self.map.next_seed()
            if seed is None:
                return

            if self.subs.check_subset(seed):
                MSS = self.subs.grow(seed)
                yield ("S", MSS)
                self.map.block_down(MSS)
            else:
                MUS = self.subs.shrink(seed)
                yield ("U", MUS)
                self.map.block_up(MUS)

    def record_delta(self, name, oldlen, newlen):
        if newlen > oldlen:
            self.stats.add_stat("delta.%s.up" % name, float(newlen - oldlen) / self.n)
        else:
            self.stats.add_stat("delta.%s.down" % name, float(oldlen - newlen) / self.n)

    def enumerate(self):
        '''MUS/MCS enumeration with all the bells and whistles...'''
        for seed, known_max in self.seeds:

            if self.config['maximize'] == 'always':
                assert not known_max
                with self.stats.time('maximize'):
                    oldlen = len(seed)
                    seed = self.map.maximize_seed(seed, direction=self.aim_high)
                    self.record_delta('max', oldlen, len(seed))

            with self.stats.time('check'):
                # subset check may improve upon seed w/ unsat_core or sat_subset
                oldlen = len(seed)
                seed_is_sat, seed = self.subs.check_subset(seed, improve_seed=True)
                self.record_delta('checkA', oldlen, len(seed))
                known_max = (known_max and (seed_is_sat == self.aim_high))

            # -m half: Only maximize if we're SAT and seeking MUSes or UNSAT and seeking MCSes
            if self.config['maximize'] == 'half' and (seed_is_sat == self.aim_high):
                assert not known_max
                # Maximize within Map and re-check satisfiability if needed
                with self.stats.time('maximize'):
                    oldlen = len(seed)
                    seed = self.map.maximize_seed(seed, direction=self.aim_high)
                    self.record_delta('max', oldlen, len(seed))
                    known_max = True
                if len(seed) != oldlen:
                    # only need to re-check if maximization produced a different seed
                    with self.stats.time('check'):
                        # improve_seed set to True in case maximized seed needs to go in opposite
                        # direction of the maximization (i.e., UNSAT seed w/ MUS aim, SAT w/ MCS aim)
                        # (otherwise, no improvement is possible as we maximized it already)
                        oldlen = len(seed)
                        seed_is_sat, seed = self.subs.check_subset(seed, improve_seed=True)
                        self.record_delta('checkB', oldlen, len(seed))
                        known_max = (len(seed) == oldlen)

            if seed_is_sat:
                if known_max:
                    MSS = seed
                else:
                    with self.stats.time('grow'):
                        oldlen = len(seed)
                        MSS = self.subs.grow(seed, inplace=True)
                        self.record_delta('grow', oldlen, len(MSS))

                yield ("S", MSS)
                self.map.block_down(MSS)

                if self.config['use_singletons']:
                    if len(MSS) == self.n - 1:
                        # singleton MCS, record to pass as hard clause to shrink()
                        singleton = self.subs.complement(MSS).pop()  # TODO: more efficient...
                        self.singleton_MCSes.add(singleton)

                if self.config['mssguided']:
                    with self.stats.time('mssguided'):
                        # don't check parents if parent is top and we've already seen it (common)
                        if len(MSS) < self.n - 1 or not self.got_top:
                            # add any unexplored superset to the queue
                            newseed = self.map.find_above(MSS)
                            if newseed:
                                self.seeds.add_seed(newseed, False)

            else:
                self.got_top = True  # any unsat set covers the top of the lattice
                if known_max:
                    MUS = seed
                else:
                    with self.stats.time('shrink'):
                        oldlen = len(seed)
                        MUS = self.subs.shrink(seed, hard=self.singleton_MCSes)
                        self.record_delta('shrink', oldlen, len(MUS))

                yield ("U", MUS)
                self.map.block_up(MUS)
                if self.config['smus']:
                    self.map.block_down(MUS)
                    self.map.block_above_size(len(MUS) - 1)


class SeedManager:
    def __init__(self, msolver, stats, config):
        self.map = msolver
        self.stats = stats
        self.config = config
        self.queue = queue.Queue()

    def __iter__(self):
        return self

    def __next__(self):
        with self.stats.time('seed'):
            if not self.queue.empty():
                return self.queue.get()
            else:
                seed, known_max = self.seed_from_solver()
                if seed is None:
                    raise StopIteration
                return seed, known_max

    def add_seed(self, seed, known_max):
        self.queue.put((seed, known_max))

    def seed_from_solver(self):
        known_max = (self.config['maximize'] == 'solver')
        return self.map.next_seed(), known_max

    # for python 2 compatibility
    next = __next__
