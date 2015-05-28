import numpy as np
import scipy.linalg
from scipy.stats.stats import spearmanr
import time
import re
import pdb
import sys
import os
import glob

class Timer(object):
    def __init__(self, name=None):
        self.name = name
        self.tstart = time.time()
        
    def __del__(self):
        if self.name:
            print '%s elapsed: %.2f' % (self.name, time.time() - self.tstart)
        else:
            print 'Elapsed: %.2f' % (time.time() - self.tstart)

# Weight: nonnegative real matrix. If not specified, return the unweighted norm
def norm1(M, Weight=None):
    if Weight is not None:
        s = np.sum( np.abs( M * Weight ) )
    else:
        s = np.sum( np.abs(M) )

    return s

def normF(M, Weight=None):
    if Weight is not None:
        # M*M: element-wise square
        s = np.sum( M * M * Weight )
    else:
        s = np.sum( M * M )

    return np.sqrt(s)

# given a list of matrices, return a list of their norms
def matSizes( norm, Ms, Weight=None ):
    sizes = []
    for M in Ms:
        sizes.append( norm(M, Weight) )
    
    return sizes

def sym(M):
    return ( M + M.T ) / 2.0

def skew(M):
    return ( M - M.T ) / 2.0

# Assume A has been approximately sorted by rows, and in each row, sorted by columns
# matrix F returned from loadBigramFile satisfies this
# print the number of elements >= A[0,0]/2^n
# return the idea cut point above which there are at least "fraction" of the elements
# these elements will be cut off to this upper limit
def getQuantileCut(A, fraction):
    totalElemCount = A.shape[0] * A.shape[1]
    maxElem = A[0,0]
    cutPoint = maxElem
    idealCutPoint = cutPoint
    
    while cutPoint >= 10:
        aboveElemCount = np.sum( A >= cutPoint )
        print "Cut point %.0f: %d" %(cutPoint, aboveElemCount)
        if aboveElemCount >= totalElemCount * fraction:
            idealCutPoint = cutPoint
        cutPoint /= 3.0
        
    return idealCutPoint
    
# find the principal eigenvalue/eigenvector: e1 & v1.
# if e1 < 0, then the left principal singular vector is -v1, and the right is v1.
# much faster than numpy.linalg.eig / scipy.linalg.eigh
def power_iter(M):
    MAXITER = 100
    epsilon = 1e-6
    vec = np.random.rand(len(M))
    old_vec = vec

    for i in xrange(MAXITER):
        vec2 = np.dot( M, vec )
        magnitude = np.linalg.norm(vec2)
        vec2 /= magnitude
        vec = vec2

        if i%2 == 1:
            error = np.linalg.norm( vec2 - old_vec )
            #print "%d: %f, %f" %( i+1, magnitude, error )
            if error < epsilon:
                break
            old_vec = vec2

    vec2 = np.dot( M, vec )
    if np.sum(vec2)/np.sum(vec) > 0:
        eigen = magnitude
    else:
        eigen = -magnitude

    return eigen, vec

# each column of vs is an eigenvector
def lowrank_fact(VV, N0):
    timer1 = Timer( "lowrank_fact()" )
        
    es, vs = np.linalg.eigh(VV)
    es = es[-N0:]
    vs = vs[ :, -N0: ]
    E_sqrt = np.diag( np.sqrt(es) )
    V = vs.dot(E_sqrt.T)
    VV = V.dot(V.T)
        
    return V, VV, vs,es

def save_embeddings( filename, vocab, V, matrixName ):
    FMAT = open(filename, "wb")
    print "Save matrix '%s' into %s" %(matrixName, filename)

    vocab_size = len(vocab)
    N = len(V[0])

    #pdb.set_trace()

    FMAT.write( "%d %d\n" %(vocab_size, N) )
    for i in xrange(vocab_size):
        line = vocab[i]
        for j in xrange(N):
            line += " %.5f" %V[i,j]
        FMAT.write("%s\n" %line)

    FMAT.close()

# for computational convenience, each row is an embedding vector
def load_embeddings( filename, maxWordCount=-1, extraWords={}, precision=np.float32 ):
    FMAT = open(filename)
    print "Load embedding text file '%s'" %(filename)
    V = []
    word2dim = {}
    vocab = []
    
    try:
        header = FMAT.readline()
        lineno = 1
        match = re.match( r"(\d+) (\d+)", header)
        if not match:
            raise ValueError(lineno, header)

        vocab_size = int(match.group(1))
        N = int(match.group(2))

        if maxWordCount > 0:
            maxWordCount = min(maxWordCount, vocab_size)
        else:
            maxWordCount = vocab_size

        print "%d extra words" %(len(extraWords))    

        # maxWordCount + len(extraWords) is the maximum num of words. 
        # V may contain extra rows that will be removed at the end
        V = np.zeros( (maxWordCount + len(extraWords), N), dtype=precision )
        wid = 0
        orig_wid = 0
        for line in FMAT:
            lineno += 1
            line = line.strip()
            # end of file
            if not line:
                if orig_wid != vocab_size:
                    raise ValueError( lineno, "%d words declared in header, but %d read" %(vocab_size, len(V)) )
                break
            
            orig_wid += 1    
            fields = line.split(' ')
            w = fields[0]
            
            if orig_wid % 1000 == 0:
                print "\r%d    %d    \r" %( orig_wid, len(extraWords) ),
            if orig_wid >= maxWordCount and w not in extraWords:
                continue
                
            V[wid] = np.array( [ float(x) for x in fields[1:] ], dtype=precision )
            word2dim[w] = wid
            vocab.append(w)
            wid += 1
            if w in extraWords:
                del extraWords[w]
            if orig_wid >= maxWordCount and len(extraWords) == 0:
                break

    except ValueError, e:
        if len( e.args ) == 2:
            print "Unknown line %d:\n%s" %( e.args[0], e.args[1] )
        else:
            exc_type, exc_obj, tb = sys.exc_info()
            print "Source line %d: %s" %(tb.tb_lineno, e)
        exit(2)
    
    FMAT.close()
    print "%d embeddings read, %d kept" %(orig_wid, wid)
    
    if wid < len(V):
        V = V[0:wid]
    return V, vocab, word2dim

# borrowed from gensim.models.word2vec
def load_embeddings_bin( filename, maxWordCount=-1, extraWords={}, precision=np.float32 ):
    print "Load embedding binary file '%s'" %(filename)
    word2dim = {}
    vocab = []
    #origWord2dim = {}
    #origVocab = []
    
    with open(filename, "rb") as fin:
        header = fin.readline()
        vocab_size, N = map(int, header.split())
        
        if maxWordCount > 0:
            maxWordCount = min(maxWordCount, vocab_size)
        else:
            maxWordCount = vocab_size

        print "%d extra words" %(len(extraWords))    
        # maxWordCount + len(extraWords) is the maximum num of words. 
        # V may contain extra rows that will be removed at the end
        V = np.zeros( (maxWordCount + len(extraWords), N), dtype=precision )
            
        full_binvec_len = np.dtype(precision).itemsize * N
        
        #pdb.set_trace()
        orig_wid = 0
        wid = 0
        while True:
            # mixed text and binary: read text first, then binary
            word = []
            while True:
                ch = fin.read(1)
                if ch == ' ':
                    break
                if ch != '\n':  # ignore newlines in front of words (some binary files have newline, some don't)
                    word.append(ch)
            word = b''.join(word)

            if word[0].isupper():
                word2 = word.lower()
                # if the lowercased word hasn't been read, treat the embedding as the lowercased word's
                # otherwise, add the capitalized word to V
                if word2 not in word2dim:
                    word = word2

            #origWord2dim[word] = orig_wid
            #origVocab.append(word)
            
            orig_wid += 1    
            if orig_wid % 1000 == 0:
                print "\r%d    %d    \r" %( orig_wid, len(extraWords) ),
            if orig_wid >= vocab_size:
                break
                
            if orig_wid >= maxWordCount and word not in extraWords:
                fin.read(full_binvec_len)
                continue
                
            word2dim[word] = wid
            vocab.append(word)
            V[wid] = np.fromstring( fin.read(full_binvec_len), dtype=precision )
            wid += 1
            if word in extraWords:
                del extraWords[word]
            if orig_wid >= maxWordCount and len(extraWords) == 0:
                break
                
    if wid < len(V):
        V = V[0:wid]
    print "%d embeddings read, %d embeddings kept" %(orig_wid, wid)
    return V, vocab, word2dim
                        
def loadBigramFile(bigram_filename, topWordNum, extraWords, kappa):
    print "Loading bigram file '%s':" %bigram_filename
    BIGRAM = open(bigram_filename)
    lineno = 0
    vocab = []
    word2dim = {}
    # 1: headers, 2: bigrams. for error msg printing
    stage = 1
    do_smoothing=True
    timer1 = Timer( "loadBigramFile()" )
    
    try:
        header = BIGRAM.readline()
        lineno += 1
        match = re.match( r"# (\d+) words, \d+ occurrences", header )
        if not match:
            raise ValueError(lineno, header)
    
        wholeVocabSize = int(match.group(1))
        print "Totally %d words"  %wholeVocabSize
        # If topWordNum < 0, read all focus words        
        if topWordNum < 0:
            topWordNum = wholeVocabSize
    
        # skip params
        header = BIGRAM.readline()
        header = BIGRAM.readline()
        lineno += 2
    
        match = re.match( r"# (\d+) bigram occurrences", header)
        if not match:
            raise ValueError(lineno, header)
    
        header = BIGRAM.readline()
        lineno += 1
    
        if header[0:6] != "Words:":
            raise ValueError(lineno, header)
    
        # vector log_u, unigram log-probs
        log_u = []
    
        i = 0
        wc = 0
        # Read the focus word list, build the word2dim mapping
        # Keep first topWordNum words and words in extraWords, if any
        while True:
            header = BIGRAM.readline()
            lineno += 1
            header = header.rstrip()
    
            # "Words" field ends
            if not header:
                break
    
            words = header.split("\t")
            for word in words:
                w, freq, log_ui = word.split(",")
                if i < topWordNum or w in extraWords:
                    word2dim[w] = i
                    log_u.append(float(log_ui))
                    vocab.append(w)
                    i += 1
                wc += 1
    
        # Usually these two should match, unless the bigram file is corrupted
        if wc != wholeVocabSize:
            raise ValueError( "%d words declared in header, but %d seen" %(wholeVocabSize, wc) )
    
        vocab_size = len(vocab)
        print "%d words seen, top %d & %d extra to keep. %d kept" %( wholeVocabSize, topWordNum, len(extraWords), vocab_size )
    
        log_u = np.array(log_u)
        u = np.exp(log_u)
        # renormalize unigram probs
        if topWordNum < wholeVocabSize:
            u = u / np.sum(u)
            log_u = np.log(u)
    
        k_u = kappa * u
        # original B, without smoothing
        #B = []
        G = np.zeros( (vocab_size, vocab_size), dtype=np.float32 )
        F = np.zeros( (vocab_size, vocab_size), dtype=np.float32 )
    
        header = BIGRAM.readline()
        lineno += 1
    
        if header[0:8] != "Bigrams:":
            raise ValueError(lineno, header)
    
        print "Read bigrams:"
        stage = 2
        
        line = BIGRAM.readline()
        lineno += 1
        wid = 0
        
        while True:
            line = line.strip()
            # end of file
            if not line:
                break
    
            # We have read the bigrams of all the wanted focus words
            if wid == vocab_size:
                # if some words in extraWords are not read, there is bug
                break
    
            orig_wid, w, neighborCount, freq, cutoffFreq = line.split(",")
            orig_wid = int(orig_wid)
    
            if orig_wid % 500 == 0:
                print "\r%d\r" %orig_wid,
    
            if orig_wid <= topWordNum or w in extraWords:
                readNeighbors = True
                # remove it from the extra list, as a double-check measure
                # when all wanted focus words are read, the extra list should be empty
                if w in extraWords:
                    del extraWords[w]
            else:
                readNeighbors = False
                   
            # x_{.j}
            x_j = np.zeros(vocab_size, dtype=np.float32)
    
            while True:
                line = BIGRAM.readline()
                lineno += 1
    
                # Empty line. Should be end of file
                if not line:
                    break
    
                # A comment. Just in case of future extension
                # Currently only the last line in the file is a comment
                if line[0] == '#':
                    continue
                    
                # beginning of the next word. Continue at the outer loop
                # Neighbor lines always start with '\t'
                if line[0] != '\t':
                    break
                
                # if the current focus word is not wanted, skip these lines
                if not readNeighbors:
                    continue
                    
                line = line.strip()
                neighbors = line.split("\t")
                for neighbor in neighbors:
                    w2, freq2, log_bij = neighbor.split(",")
                    # words not in vocab are ignored
                    if w2 in word2dim:
                        i = word2dim[w2]
                        x_j[i] = int(freq2)
    
            # B stores original probs
            #B.append( x_j / np.sum(x_j) )
    
            # only push to F & G when the focus word is wanted
            if readNeighbors:
                # append a copy of x_j by * 1
                # otherwise only append a pointer. The contents may be changed accidentally elsewhere
                # the freqs are transformed and used as weights
        
                # smoothing using ( total freq of w )^0.7
                if do_smoothing:
                    x_j_norm1 = norm1(x_j)
                    utrans = x_j_norm1 * k_u
                    x_j += utrans
                    #x_j_norm2 = norm1(x_j)
                    #smooth_norm = norm1(utrans)
                    #if wid % 50 == 0:
                    #    print "%d,%d: smoothing %.5f/%.5f. %d -> %d" %( orig_wid, wid+1, smooth_norm, smooth_norm/x_j_norm1, 
                    #                                                        x_j_norm1, x_j_norm2 )
                        
                F[wid] = x_j
        
                # normalization
                b_j = x_j / np.sum(x_j)
                
                logb_j = np.log(b_j)
                G[wid] = logb_j - log_u
                wid += 1
    
    except ValueError, e:
        if len( e.args ) == 2:
            print "Unknown line %d:\n%s" %( e.args[0], e.args[1] )
        else:
            exc_type, exc_obj, tb = sys.exc_info()
            print "Source line %d: %s" %(tb.tb_lineno, e)
            if stage == 1:
                print header
            else:
                print line
        exit(0)
    
    print
    BIGRAM.close()
    
    return vocab, word2dim, G, F, u

def loadUnigramFile(filename):
    UNI = open(filename)
    vocab_dict = {}
    i = 1
    for line in UNI:
        line = line.strip()
        if line[0] == '#':
            continue
        fields = line.split("\t")
                             # id, freq, log prob
        vocab_dict[ fields[0] ] = (i, fields[1], fields[2])
        i += 1
    
    return vocab_dict

def loadExtraWordFile(filename):
    extraWords = {}
    with open(filename) as f:
        for line in f:
            w, wid = line.strip().split('\t')
            extraWords[w] = 1

    return extraWords   
    
# borrowed from Omer Levy's code
def loadSimTestset(path):
    testset = []
    print "Read sim testset " + path
    with open(path) as f:
        for line in f:
            x, y, sim = line.strip().lower().split()
            testset.append( [ x, y, float(sim) ] )
    return testset

def loadAnaTestset(path):
    testset = []
    print "Read analogy testset " + path
    with open(path) as f:
        for line in f:
            a, a2, b, b2 = line.strip().lower().split()
            testset.append( [ a, a2, b, b2 ] )
    return testset

def loadTestsets(loader, testsetDir, testsetNames):
    # always use unix style path
    testsetDir = testsetDir.replace("\\", "/")
    if testsetDir[-1] != '/':
        testsetDir += '/'
    
    if not os.path.isdir(testsetDir):
        print "ERR: Test set dir does not exist or is not a dir:\n" + testsetDir
        sys.exit(2)
    
    testsets = []
    if len(testsetNames) == 0:
        testsetNames = glob.glob( testsetDir + '*.txt' )
        if len(testsetNames) == 0:
            print "No testset ended with '.txt' is found in " + testsetDir
            sys.exit(2)
        testsetNames = map( lambda x: os.path.basename(x)[:-4], testsetNames )
            
    for testsetName in testsetNames:
        testset = loader( testsetDir + testsetName + ".txt" )
        testsets.append(testset)
    
    return testsets
    
# "model" in methods below has to support two methods:
# model[w]: return the embedding of w
# model.similarity(x, y): return the cosine similarity between the embeddings of x and y
# realb2 is passed in only for debugging purpose
def predict_ana( model, a, a2, b, realb2 ):
    questWordIndices = [ model.word2dim[x] for x in (a,a2,b) ]
    # b2 is effectively iterating through the vocab. The row is all the cosine values
    b2a2 = model.sim_row(a2)
    b2a  = model.sim_row(a)
    b2b  = model.sim_row(b)
    addsims = b2a2 - b2a + b2b

    addsims[questWordIndices] = -10000

    iadd = np.nanargmax(addsims)
    b2add  = model.vocab[iadd]

    # For debugging purposes
    ia = model.word2dim[a]
    ia2 = model.word2dim[a2]
    ib = model.word2dim[b]
    ib2 = model.word2dim[realb2]
    realaddsim = addsims[ib2]
    
    """
    mulsims = b2a2 * b2b / ( b2a + 0.01 )            
    baa2 = model[b] - model[a] + model[a2]
    baa2 = baa2/normF(baa2)
    sims2 = model.V.dot(baa2)
    dists1 = np.abs( model.V - baa2 ).dot( np.ones( model.V.shape[1] ) )

    mulsims[questWordIndices] = -10000
    sims2[questWordIndices] = -10000
    dists1[questWordIndices] = 10000

    imul = np.nanargmax(mulsims)
    b2mul  = model.vocab[imul]

    i2 = np.nanargmax(sims2)
    b22 = model.vocab[i2]
    i1 = np.nanargmin(dists1)
    b21 = model.vocab[i1]

    realsim2 = sims2[ib2]
    realdist1 = dists1[ib2]
    
    # F-norm (L2)
    topIDs2 = sims2.argsort()[-5:][::-1]
    topwords2 = [ model.vocab[i] for i in topIDs2 ]
    topsims2 = sims2[topIDs2]
    
    # Manhattan distance (L1)
    topIDs1 = sims1.argsort()[-5:][::-1]
    topwords1 = [ model.vocab[i] for i in topIDs1 ]
    topsims1 = sims1[topIDs1]
    
    if b22 != realb2:
        print "%s,%s\t%s,[%s]" %(a,a2,b,realb2)
        print "%s,%f\t%s\t%s" %(b21,realsim1, str(topsims1), str(topwords1))
        print "%s,%f\t%s\t%s" %(b22,realsim2, str(topsims2), str(topwords2))
        print
        #pdb.set_trace()
    return b2add, b2mul, b21, b22
    """
    
    return b2add

# vocab_dict is a vocabulary dict, usually bigger than model.vocab, loaded from a unigram file
# its purpose is to find absent words in the model
def evaluate_sim(model, testsets, testsetNames, getAbsentWords=False, vocab_dict=None, cutPoint=0 ):

    # words in the vocab but not in the model
    absentModelID2Word = {}
    # words not in the vocab (of coz not in the model)
    absentVocabWords = {}
    # words in the vocab but below the cutPoint (id > cutPoint), may be in or out of the model
    cutVocabWords = {}
    # a set of spearman coeffs, in the same order as in testsets
    spearmanCoeff = []
    
    for i,testset in enumerate(testsets):
        modelResults = []
        groundtruth = []
        
        for x, y, sim in testset:
            if vocab_dict and x in vocab_dict:
                xid = vocab_dict[x][0]
                if cutPoint > 0 and xid > cutPoint:
                    cutVocabWords[x] = 1
                    
            if vocab_dict and y in vocab_dict:                    
                yid = vocab_dict[y][0]
                if cutPoint > 0 and yid > cutPoint:
                    cutVocabWords[y] = 1
            
            if x not in model:
                if getAbsentWords and x in vocab_dict:
                    absentModelID2Word[xid] = x
                else:
                    absentVocabWords[x] = 1
            elif y not in model:
                if getAbsentWords and y in vocab_dict:
                    absentModelID2Word[yid] = y
                else:
                    absentVocabWords[y] = 1
            else:
                modelResults.append( model.similarity(x, y) )
                groundtruth.append(sim)
                #print "%s %s: %.3f %.3f" %(x, y, modelResults[-1], sim)
        print "%s: %d test pairs, %d valid" %( testsetNames[i], len(testset), len(modelResults) ),
        spearmanCoeff.append( spearmanr(modelResults, groundtruth)[0] )
        print ", %.5f" %spearmanCoeff[-1]

    # return hashes directly, for ease of merge    
    return spearmanCoeff, absentModelID2Word, absentVocabWords, cutVocabWords

# vocab_dict is a vocabulary dict, usually bigger than model.vocab, loaded from a unigram file
# its purpose is to find absent words in the model
def evaluate_ana(model, testsets, testsetNames, getAbsentWords=False, vocab_dict=None, cutPoint=0 ):
    # for words in the vocab but not in the model. mapping from words to IDs
    absentModelID2Word = {}
    # words not in the vocab (of coz not in the model)
    absentVocabWords = {}
    # words in the vocab but below the cutPoint (id > cutPoint), may be in or out of the model
    cutVocabWords = {}
    # a set of scores, in the same order as in testsets
    # each is a tuple (add_score, mul_score)
    anaScores = []
    
    #pdb.set_trace()
    
    for i,testset in enumerate(testsets):
        modelResults = []
        groundtruth = []

        correct_add = 0.0
#        correct_mul = 0.0
#        correct_L1 = 0.0
#        correct_L2 = 0.0
        validPairNum = 0
        currentScore = 0.0
        
        for j,analogy in enumerate(testset):
                
            allWordsPresent = True
            watchWhenWrong = False
            
            for x in analogy:
                if vocab_dict and x in vocab_dict:
                    xid = vocab_dict[x][0]
                    if cutPoint > 0 and xid > cutPoint:
                        cutVocabWords[x] = 1
                        watchWhenWrong = True
                        
                if x not in model:
                    if vocab_dict and x in vocab_dict:
                        absentModelID2Word[ vocab_dict[x][0] ] = x
                    else:
                        absentVocabWords[x] = 1
                    allWordsPresent = False
                    
            if allWordsPresent:
                a, a2, b, b2 = analogy
                b2_add = predict_ana( model, a, a2, b, b2 )
                validPairNum += 1
                if b2_add == b2:
                    correct_add += 1
                elif watchWhenWrong:
                    print "%s~%s = %s~%s,%.3f (%s,%3f)" %( a, a2, b, b2, model.similarity(b,b2), b2_add, model.similarity(b,b2_add) )
                    
                """if b2_mul == b2:
                    correct_mul += 1
                if b2_L1 == b2:    
                    correct_L1 += 1    
                if b2_L2 == b2:    
                    correct_L2 += 1
                currentScores = np.array([ correct_add, correct_mul, correct_L1, correct_L2 ]) / validPairNum
                """    

                currentScore = correct_add / validPairNum
                
            if j % 500 == 499:
                print "\r%i/%i/%i: %.5f\r" %( j + 1, validPairNum, len(testset), currentScore ),
                
        print "\n%s: %d analogies, %d valid" %( testsetNames[i], len(testset), validPairNum ),
        anaScores.append(currentScore)
        print ". AddSim Score: %.5f" %currentScore

    return anaScores, absentModelID2Word, absentVocabWords, cutVocabWords

def bench(func, N, topEigenNum=0):
    print "Begin to factorize a %dx%d matrix" %(N,N)
    a = np.random.randn(N, N)
    a = (a+a.T)/2
    tic = time.clock()
    func(a)
    toc = time.clock()
    diff = toc - tic
    print "Elapsed time is %.3f" %diff
    return diff
        
class vecModel:
    def __init__(self, V, vocab, word2dim, vecNormalize=True):
        self.Vorig = V
        self.V = np.array([ x/normF(x) for x in self.Vorig ])
        self.word2dim = word2dim
        self.vecNormalize = vecNormalize
        self.vocab = vocab
        self.iterIndex = 0
        self.cosTable = None
        
    def __contains__(self, w):
        return w in self.word2dim
        
    def __getitem__(self, w):
        if w not in self:
            return None
        else:
            if self.vecNormalize:
                return self.V[ self.word2dim[w] ]
            else:
                return self.Vorig[ self.word2dim[w] ]

    def orig(self, w):
        if w not in self:
            return None
        else:
            return self.Vorig[ self.word2dim[w] ]
    
    def precompute_cosine(self):
        print "Precompute cosine matrix...",
        self.cosTable = np.dot( self.V, self.V.T )
        print "Done."
        
    def similarity(self, x, y):
        if x not in self or y not in self:
            return 0
        
        if self.vecNormalize:
            if self.cosTable is not None:
                ix = self.word2dim[x]
                iy = self.word2dim[y]
                return self.cosTable[ix,iy]
            return np.dot( self[x], self[y] )
        
        # when vectors are not normalized, return the raw dot product                        
        vx = self[x]
        vy = self[y]
        # vector too short. the similarity doesn't make sense
        if normF(vx) <= 1e-6 or normF(vy) <= 1e-6:
            return 0
        
        return np.dot( self[x], self[y] )

    def sim_row(self, x):
        if x not in self:
            return 0
        
        if self.vecNormalize:
            if self.cosTable is None:
                self.precompute_cosine()
            ix = self.word2dim[x]
            return self.cosTable[ix]
                    
        vx = self[x]
        # vector too short. the dot product similarity doesn't make sense
        if normF(vx) <= 1e-6:
            return np.zeros( len(self.vocab) )
        
        return self.V.dot(vx)

            