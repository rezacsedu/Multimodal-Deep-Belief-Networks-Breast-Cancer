from __future__ import print_function, division
import os
import sys
import timeit
from itertools import cycle

import numpy
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics.classification import accuracy_score
from sklearn.metrics import precision_recall_fscore_support
from sklearn.metrics import confusion_matrix
from sklearn.decomposition import PCA
from sklearn.metrics import roc_curve, auc
from sklearn.preprocessing import label_binarize
import itertools
import matplotlib.pyplot as plt

import theano
import theano.tensor as T
from theano.sandbox.rng_mrg import MRG_RandomStreams

from dataset_location import *


def print_and_plot_confusion_matrix(cm, classes, normalize=False, title='Confusion matrix', cmap=plt.cm.Blues):
    """
    This function prints and plots the confusion matrix.
    Normalization can be applied by setting `normalize=True`.
    """
    plt.imshow(cm, interpolation='nearest', cmap=cmap)
    plt.title(title)
    plt.colorbar()
    tick_marks = numpy.arange(len(classes))
    plt.xticks(tick_marks, classes, rotation=45)
    plt.yticks(tick_marks, classes)

    if normalize:
        cm = cm.astype('float') / cm.sum(axis=1)[:, numpy.newaxis]
        print("Normalized confusion matrix")
    else:
        print('Confusion matrix, without normalization')

    thresh = cm.max() / 2.
    for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
        plt.text(j, i, cm[i, j], horizontalalignment="center", color="white" if cm[i, j] > thresh else "black")

    plt.tight_layout()
    plt.ylabel('True label')
    plt.xlabel('Predicted label')
    return cm


def shared_dataset(data_xy, borrow=True):
    """ Function that loads the dataset into shared variables

    The reason we store our dataset in shared variables is to allow
    Theano to copy it into the GPU memory (when code is run on GPU).
    Since copying data into the GPU is slow, copying a minibatch everytime
    is needed (the default behaviour if the data is not in a shared
    variable) would lead to a large decrease in performance.
    """
    data_x, data_y = data_xy
    shared_x = theano.shared(numpy.asarray(data_x, dtype=theano.config.floatX), borrow=borrow)
    shared_y = theano.shared(numpy.asarray(data_y, dtype=theano.config.floatX), borrow=borrow)
    # When storing data on the GPU it has to be stored as floats
    # therefore we will store the labels as ``floatX`` as well
    # (``shared_y`` does exactly that). But during our computations
    # we need them as ints (we use labels as index, and if they are
    # floats it doesn't make sense) therefore instead of returning
    # ``shared_y`` we will have to cast it to int. This little hack
    # lets ous get around this issue
    return shared_x, T.cast(shared_y, 'int32')


def load_data(dataset, pca=2):
    """ The load dataset function
    
    This function covers for singular dataset
    (either DNA Methylation, Gene Expression, or miRNA Expression)
    for ER, PGR, and HER2 status prediction.
    Input is .npy file location in string format.
    Output is in Theano shared variable format
    to speed up computation with GPU.
    """
    
    # Initialize list of dataset files' name
    temp_input = []
    temp_label = []

    # Input list of dataset files' name
    if dataset == 1:        # Methylation Platform GPL8490  (27578 cpg sites)
        temp_input.extend((INPUT_MET_TYPE_ER,INPUT_MET_TYPE_PGR,INPUT_MET_TYPE_HER2))
        temp_label.extend((LABELS_MET_TYPE_ER,LABELS_MET_TYPE_PGR,LABELS_MET_TYPE_HER2))
    elif dataset == 2:      # Methylation Platform GPL16304 (485577 cpg sites)
        temp_input.extend((INPUT_METLONG_TYPE_ER,INPUT_METLONG_TYPE_PGR,INPUT_METLONG_TYPE_HER2))
        temp_label.extend((LABELS_METLONG_TYPE_ER,LABELS_METLONG_TYPE_PGR,LABELS_METLONG_TYPE_HER2))
    elif (dataset == 3) or (dataset == 4) or (dataset == 5):    # Gene
        temp_label.extend((LABELS_GEN_TYPE_ER,LABELS_GEN_TYPE_PGR,LABELS_GEN_TYPE_HER2))
        if dataset == 3:    # Gene Count
            temp_input.extend((INPUT_GEN_TYPE_ER_COUNT,INPUT_GEN_TYPE_PGR_COUNT,INPUT_GEN_TYPE_HER2_COUNT))
        elif dataset == 4:  # Gene FPKM
            temp_input.extend((INPUT_GEN_TYPE_ER_FPKM,INPUT_GEN_TYPE_PGR_FPKM,INPUT_GEN_TYPE_HER2_FPKM))
        elif dataset == 5:  # Gene FPKM-UQ
            temp_input.extend((INPUT_GEN_TYPE_ER_FPKMUQ,INPUT_GEN_TYPE_PGR_FPKMUQ,INPUT_GEN_TYPE_HER2_FPKMUQ))
    elif dataset == 6:      # miRNA
        temp_input.extend((INPUT_MIR_TYPE_ER,INPUT_MIR_TYPE_PGR,INPUT_MIR_TYPE_HER2))
        temp_label.extend((LABELS_MIR_TYPE_ER,LABELS_MIR_TYPE_PGR,LABELS_MIR_TYPE_HER2))

    
    min_max_scaler = MinMaxScaler()     # Initialize normalization function
    rval = []                           # Initialize list of outputs

    # Iterate 3 times, each for ER, PGR, and HER2
    for i in range(3):
        # Load the dataset as 'numpy.ndarray'
        try:
            input_set = numpy.load(temp_input[i])
            label_set = numpy.load(temp_label[i])
        except Exception as e:
            sys.exit("Change your choice of features because the data is not available")

        # feature selection by PCA
        if pca == 1:
            pca0 = PCA(n_components=600)
            input_set = pca0.fit_transform(input_set)

        # normalize input
        input_set = min_max_scaler.fit_transform(input_set)

        rval.extend((input_set, label_set))

    return rval


class LogisticRegression(object):
    """ Logistic Regression class
    
    Logistic regression consist of 1 input layer and 1 output layer.
    It functions as the last 2 layers of the DBN.
    The output layer uses softmax as the activation function.
    The cost function is negative log likelihood function.
    """

    def __init__(self, input, n_in, n_out, dropout=0.):
        """ Logistic Regression initialization function

        Logistic Regression is defined by input of Theano tensor matrix variable,
        size of input layer, and size of output layer.
        Logistic regression parameters (weight and bias) are created based on these.
        The predicted output uses softmax as activation function.
        Predicted label is neuron in output layer with highest value.
        """
        self.input = input

        self.W = theano.shared(value=numpy.zeros((n_in, n_out), dtype=theano.config.floatX), name='W', borrow=True)
        self.b = theano.shared(value=numpy.zeros((n_out,), dtype=theano.config.floatX), name='b', borrow=True)
        self.params = [self.W, self.b]

        srng = MRG_RandomStreams()

        # Dropout
        retain_prob = 1 - dropout
        input *= srng.binomial(input.shape, p=retain_prob, dtype=theano.config.floatX)
        input /= retain_prob

        self.p_y_given_x = T.nnet.softmax(T.dot(input + dropout, self.W) + self.b)
        

    def negative_log_likelihood(self, y):
        """ Logistic Regression negative log likelihood cost function

        The cost function is calculated using the predicted output and the actual output.
        """
        return -T.mean(T.log(self.p_y_given_x)[T.arange(y.shape[0]), y])
        
    def y_predict(self):
        """ Logistic Regression predicted output function """
        return T.argmax(self.p_y_given_x, axis=1)
        
    def y_predict_onehot(self):
        """ Logistic Regression predicted output function """
        return self.p_y_given_x


class HiddenLayer(object):
    """ Hidden Layer class
    
    It defines a hidden layer with adjustable activation function.
    """
    
    def __init__(self, rng, input, n_in, n_out, W=None, b=None, activation=T.tanh):
        """ Hidden Layer initialization function

        Hidden Layer is defined by input of Theano tensor matrix variable,
        size of input layer, and size of output layer.
        Hidden layer parameters (weight and bias) are created based on these.
        """
        self.input = input
        
        if W is None:
            W_values = numpy.asarray(rng.uniform(low=-numpy.sqrt(6. / (n_in + n_out)), high=numpy.sqrt(6. / (n_in + n_out)), size=(n_in, n_out)), dtype=theano.config.floatX)
            if activation == theano.tensor.nnet.sigmoid:
                W_values *= 4

            W = theano.shared(value=W_values, name='W', borrow=True)

        if b is None:
            b_values = numpy.zeros((n_out,), dtype=theano.config.floatX)
            b = theano.shared(value=b_values, name='b', borrow=True)

        self.W = W
        self.b = b

        lin_output = T.dot(input, self.W) + self.b
        self.output = (lin_output if activation is None else activation(lin_output))
        self.params = [self.W, self.b]


class RBM(object):
    """ RBM class
    
    It implements either Contrastive Divergence (CD) or Persistent Contrastive Divergence (PCD).
    """

    def __init__(self, input=None, n_visible=784, n_hidden=500, W=None, hbias=None, vbias=None, numpy_rng=None, theano_rng=None):
        """ RBM initialization function

        Defines the parameters of the model along with
        basic operations for inferring hidden from visible (and vice-versa),
        as well as for performing Contrastive Divergence updates.

        :param input: None for standalone RBMs or symbolic variable if RBM is
        part of a larger graph.

        :param n_visible: number of visible units

        :param n_hidden: number of hidden units

        :param W: None for standalone RBMs or symbolic variable pointing to a
        shared weight matrix in case RBM is part of a DBN network; in a DBN,
        the weights are shared between RBMs and layers of a MLP

        :param hbias: None for standalone RBMs or symbolic variable pointing
        to a shared hidden units bias vector in case RBM is part of a
        different network

        :param vbias: None for standalone RBMs or a symbolic variable
        pointing to a shared visible units bias
        """
        self.n_visible = n_visible
        self.n_hidden = n_hidden

        if numpy_rng is None:
            numpy_rng = numpy.random.RandomState(1234)

        if theano_rng is None:
            theano_rng = RandomStreams(numpy_rng.randint(2 ** 30))

        if W is None:
            initial_W = numpy.asarray(numpy_rng.uniform(low=-4 * numpy.sqrt(6. / (n_hidden + n_visible)), high=4 * numpy.sqrt(6. / (n_hidden + n_visible)), size=(n_visible, n_hidden)), dtype=theano.config.floatX)
            W = theano.shared(value=initial_W, name='W', borrow=True)

        if hbias is None:
            hbias = theano.shared(value=numpy.zeros(n_hidden, dtype=theano.config.floatX), name='hbias', borrow=True)

        if vbias is None:
            vbias = theano.shared(value=numpy.zeros(n_visible, dtype=theano.config.floatX), name='vbias', borrow=True)

        self.input = input
        if not input:
            self.input = T.matrix('input')

        self.W = W
        self.hbias = hbias
        self.vbias = vbias
        self.theano_rng = theano_rng
        self.params = [self.W, self.hbias, self.vbias]
        
    def free_energy(self, v_sample):
        """ Free Energy function """
        wx_b = T.dot(v_sample, self.W) + self.hbias
        vbias_term = T.dot(v_sample, self.vbias)
        hidden_term = T.sum(T.log(1 + T.exp(wx_b)), axis=1)
        return -hidden_term - vbias_term

    def propup(self, vis):
        """ Propup function 

        This function propagates the visible units activation upwards to
        the hidden units
        """
        pre_sigmoid_activation = T.dot(vis, self.W) + self.hbias
        return [pre_sigmoid_activation, T.nnet.sigmoid(pre_sigmoid_activation)]

    def sample_h_given_v(self, v0_sample):
        """ Sample H given V function 

        This function propagates the visible units activation upwards to
        the hidden units, then take a sample of the hidden units given
        their activation functions.
        
        For GPU usage, specify theano_rng.binomial to return the dtype floatX
        """
        pre_sigmoid_h1, h1_mean = self.propup(v0_sample)
        h1_sample = self.theano_rng.binomial(size=h1_mean.shape, n=1, p=h1_mean, dtype=theano.config.floatX)
        return [pre_sigmoid_h1, h1_mean, h1_sample]

    def propdown(self, hid):
        """ Propup function 

        This function propagates the hidden units activation downwards to
        the visible units
        """
        pre_sigmoid_activation = T.dot(hid, self.W.T) + self.vbias
        return [pre_sigmoid_activation, T.nnet.sigmoid(pre_sigmoid_activation)]

    def sample_v_given_h(self, h0_sample):
        """ Sample H given V function 

        This function propagates the hidden units activation downwards to
        the visible units, then take a sample of the visible units given
        their activation functions.
        
        For GPU usage, specify theano_rng.binomial to return the dtype floatX
        """
        pre_sigmoid_v1, v1_mean = self.propdown(h0_sample)
        v1_sample = self.theano_rng.binomial(size=v1_mean.shape, n=1, p=v1_mean, dtype=theano.config.floatX)
        return [pre_sigmoid_v1, v1_mean, v1_sample]

    def gibbs_hvh(self, h0_sample):
        """ Gibbs HVH function 

        This function performs one step of Gibbs sampling starting from the hidden state
        """
        pre_sigmoid_v1, v1_mean, v1_sample = self.sample_v_given_h(h0_sample)
        pre_sigmoid_h1, h1_mean, h1_sample = self.sample_h_given_v(v1_sample)
        return [pre_sigmoid_v1, v1_mean, v1_sample, pre_sigmoid_h1, h1_mean, h1_sample]

    def gibbs_vhv(self, v0_sample):
        """ Gibbs VHV function 

        This function performs one step of Gibbs sampling starting from the visible state
        """
        pre_sigmoid_h1, h1_mean, h1_sample = self.sample_h_given_v(v0_sample)
        pre_sigmoid_v1, v1_mean, v1_sample = self.sample_v_given_h(h1_sample)
        return [pre_sigmoid_h1, h1_mean, h1_sample,
                pre_sigmoid_v1, v1_mean, v1_sample]

    def get_cost_updates(self, lr=0.1, persistent=None, k=1):
        """ Get Cost Updates function

        This functions implements one step of Contrastive Divergence (CD)
        or Persistent Contrastive Divergence (PCD)

        :param persistent: None for CD. For PCD, shared variable
            containing old state of Gibbs chain. This must be a shared
            variable of size (batch size, number of hidden units).

        :param k: number of Gibbs steps to do in CD-k/PCD-k

        Returns monitoring cost and the updated dictionary. The
        dictionary contains the update rules for weights and biases but
        also an update of the shared variable used to store the persistent
        chain, if PCD is used.
        """

        # compute positive phase for CD
        pre_sigmoid_ph, ph_mean, ph_sample = self.sample_h_given_v(self.input)

        # determine start of the chain
        # CD uses newly generated hidden state
        # PCD uses the old state of the chain
        if persistent is None:
            chain_start = ph_sample
        else:
            chain_start = persistent
        
        # Gibbs sampling for k steps to find the end of the chain
        ([pre_sigmoid_nvs, nv_means, nv_samples, pre_sigmoid_nhs, nh_means, nh_samples], updates) = theano.scan(self.gibbs_hvh, outputs_info=[None, None, None, None, None, chain_start], n_steps=k, name="gibbs_hvh")
        chain_end = nv_samples[-1]

        # Cost function and parameter updates
        cost = T.mean(self.free_energy(self.input)) - T.mean(self.free_energy(chain_end))
        gparams = T.grad(cost, self.params, consider_constant=[chain_end])
        for gparam, param in zip(gparams, self.params):
            updates[param] = param - gparam * T.cast(lr, dtype=theano.config.floatX)
        
        # Monitoring cost
        # For PCD, update the persistent variable with the end of current chain
        if persistent:
            updates[persistent] = nh_samples[-1]
            monitoring_cost = self.get_pseudo_likelihood_cost(updates)
        else:
            monitoring_cost = self.get_reconstruction_cost(updates, pre_sigmoid_nvs[-1])

        return monitoring_cost, updates
        
    def get_pseudo_likelihood_cost(self, updates):
        """ Pseudo Likelihood Cost function 

        Monitoring cost for PCD.
        """

        bit_i_idx = theano.shared(value=0, name='bit_i_idx')

        xi = T.round(self.input)

        fe_xi = self.free_energy(xi)

        xi_flip = T.set_subtensor(xi[:, bit_i_idx], 1 - xi[:, bit_i_idx])
        fe_xi_flip = self.free_energy(xi_flip)

        cost = T.mean(self.n_visible * T.log(T.nnet.sigmoid(fe_xi_flip - fe_xi)))
        updates[bit_i_idx] = (bit_i_idx + 1) % self.n_visible

        return cost

    def get_reconstruction_cost(self, updates, pre_sigmoid_nv):
        """ Reconstruction Cost function 

        Monitoring cost for CD.
        """
        cross_entropy = T.mean(T.sum(self.input * T.log(T.nnet.sigmoid(pre_sigmoid_nv)) + (1 - self.input) * T.log(1 - T.nnet.sigmoid(pre_sigmoid_nv)), axis=1))
        return cross_entropy


class DBN(object):
    """ DBN class
    
    DBN consist of 1 input layer, at least 1 of hidden layer, and 1 output layer.
    The initialization define the rbm and sigmoid layer as the hidden layer, and a logistic regression as the output layer
    The output layer uses softmax as the activation function.
    The cost function is negative log likelihood function.
    """

    def __init__(self, numpy_rng, theano_rng=None, n_ins=784, hidden_layers_sizes=[500, 500], n_outs=3):
        """ DBN initialization function

        DBN is defined by size of input layer, hidden layers, output layer.
        This function defines the 
        DBN parameters (weight and bias) are created based on these.
        The predicted output uses softmax as activation function.
        Predicted label is neuron in output layer with highest value.
        """
        self.sigmoid_layers = []
        self.rbm_layers = []
        self.params = []
        self.n_layers = len(hidden_layers_sizes)

        assert self.n_layers > 0

        if not theano_rng:
            theano_rng = MRG_RandomStreams(numpy_rng.randint(2 ** 30))

        self.x = T.matrix('x')
        self.y = T.ivector('y')
        self.dropout = T.dscalar('dropout')
        
        # Iterate for as many numbers of hidden layers
        # So, the size of sigmoid_layers and rbm_layers is the same as the size of hidden layers
        for i in range(self.n_layers):
            if i == 0:
                input_size = n_ins
            else:
                input_size = hidden_layers_sizes[i - 1]

            if i == 0:
                layer_input = self.x
            else:
                layer_input = self.sigmoid_layers[-1].output

            # Sigmoid hidden layers
            sigmoid_layer = HiddenLayer(rng=numpy_rng,
                input=layer_input,
                n_in=input_size,
                n_out=hidden_layers_sizes[i],
                activation=T.nnet.sigmoid)

            self.sigmoid_layers.append(sigmoid_layer)

            self.params.extend(sigmoid_layer.params)

            # RBM hidden layers
            # RBM shares its weights and hidden biases with the sigmoid layers
            rbm_layer = RBM(numpy_rng=numpy_rng,
                theano_rng=theano_rng,
                input=layer_input,
                n_visible=input_size,
                n_hidden=hidden_layers_sizes[i],
                W=sigmoid_layer.W,
                hbias=sigmoid_layer.b)
            
            self.rbm_layers.append(rbm_layer)

        # Logistic Regression output layer
        self.logLayer = LogisticRegression(input=self.sigmoid_layers[-1].output,
                                           n_in=hidden_layers_sizes[-1],
                                           n_out=n_outs,
                                           dropout=self.dropout)
        
        self.params.extend(self.logLayer.params)

        # cost function
        self.finetune_cost = self.logLayer.negative_log_likelihood(self.y)

        # predicted output function
        self.y_predict = self.logLayer.y_predict()

        # predicted output function
        self.y_predict_onehot = self.logLayer.y_predict_onehot()

    def pretraining_functions(self, train_set_x, batch_size, k):
        """ DBN Pretraining function

        It implements series of RBMs.
        The default is using CD (persistent=None).
        The output is series of RBM functions.
        Each function updates paratemers on each RBM and outputs a monitoring cost.
        """
        index = T.lscalar('index')
        learning_rate = T.scalar('lr')

        batch_begin = index * batch_size
        batch_end = batch_begin + batch_size

        pretrain_fns = []
        for rbm in self.rbm_layers:
            cost, updates = rbm.get_cost_updates(learning_rate, persistent=None, k=k)

            fn = theano.function(inputs=[index, theano.In(learning_rate, value=0.1)],
                                 outputs=cost,
                                 updates=updates,
                                 givens={self.x: train_set_x[batch_begin:batch_end]})
            pretrain_fns.append(fn)

        return pretrain_fns

    def build_finetune_functions(self, train_set_x, train_set_y, batch_size, learning_rate, dropout=0., optimizer=1):
        """ DBN Finetune function

        Implement train function
        All functions done per batch size
        Train function results in the finetune cost (negative log likelihood cost) and parameter update
        """

        index = T.lscalar('index')

        # Parameter update
        def SGD(cost, params, lr=0.0002):
            updates = []
            grads = T.grad(cost, params)
            for p, g in zip(params, grads):
                updates.append((p, p - g * lr))
            return updates

        def RMSprop(cost, params, lr=0.0002, rho=0.9, epsilon=1e-6):
            grads = T.grad(cost=cost, wrt=params)
            updates = []
            for p, g in zip(params, grads):
                acc = theano.shared(p.get_value() * 0.)
                acc_new = rho * acc + (1 - rho) * g ** 2
                gradient_scaling = T.sqrt(acc_new + epsilon)
                g = g / gradient_scaling
                updates.append((acc, acc_new))
                updates.append((p, p - lr * g))
            return updates

        def Adam(cost, params, lr=0.0002, b1=0.1, b2=0.001, e=1e-8):
            updates = []
            grads = T.grad(cost, params)
            i = theano.shared(numpy.asarray(0., dtype=theano.config.floatX))
            i_t = i + 1.
            fix1 = 1. - (1. - b1)**i_t
            fix2 = 1. - (1. - b2)**i_t
            lr_t = lr * (T.sqrt(fix2) / fix1)
            for p, g in zip(params, grads):
                m = theano.shared(p.get_value() * 0.)
                v = theano.shared(p.get_value() * 0.)
                m_t = (b1 * g) + ((1. - b1) * m)
                v_t = (b2 * T.sqr(g)) + ((1. - b2) * v)
                g_t = m_t / (T.sqrt(v_t) + e)
                p_t = p - (lr_t * g_t)
                updates.append((m, m_t))
                updates.append((v, v_t))
                updates.append((p, p_t))
            updates.append((i, i_t))
            return updates

        if optimizer == 1:
            updates = SGD(cost=self.finetune_cost, params=self.params, lr=learning_rate)
        elif optimizer == 2:
            updates = RMSprop(cost=self.finetune_cost, params=self.params, lr=learning_rate)
        elif optimizer == 3:
            updates = Adam(cost=self.finetune_cost, params=self.params, lr=learning_rate)

        # train function
        train_fn = theano.function(inputs=[index],
            outputs=self.finetune_cost,
            updates=updates,
            givens={self.x: train_set_x[index * batch_size: (index + 1) * batch_size],
                    self.y: train_set_y[index * batch_size: (index + 1) * batch_size],
                    self.dropout: dropout})

        return train_fn

    def predict(self, test_set_x, dropout=0.):
        """ Predict function

        Predict the output of the test input
        """

        index = T.lscalar('index')

        # test function
        test_score_i = theano.function([index],
            self.y_predict,
            on_unused_input='ignore',
            givens={self.x: test_set_x[index:],
                    self.dropout: 0.})

        def test_score():
            return test_score_i(0)

        return test_score

    def predict_onehot(self, test_set_x, dropout=0.):
        """ Predict function

        Predict the output of the test input
        """

        index = T.lscalar('index')

        # test function
        test_score_i = theano.function([index],
            self.y_predict_onehot,
            on_unused_input='ignore',
            givens={self.x: test_set_x[index:],
                    self.dropout: 0.})

        def test_score():
            return test_score_i(0)

        return test_score


def test_DBN(finetune_lr=0.1,
    pretraining_epochs=100,
    pretrain_lr=0.01,
    k=1,
    training_epochs=100,
    dataset=6,
    batch_size=10,
    layers=[1000, 1000, 1000],
    dropout=0.2,
    pca=2,
    optimizer=1):
    
    # Title
    temp_title = ["DNA Methylation Platform GPL8490",
                  "DNA Methylation Platform GPL16304",
                  "Gene Expression HTSeq Count",
                  "Gene Expression HTSeq FPKM",
                  "Gene Expression HTSeq FPKM-UQ",
                  "miRNA Expression"]
    print("\nCancer Type Classification with " + temp_title[dataset-1] + " (Theano)\n")
    
    # Load datasets
    datasets = load_data(dataset, pca)

    temp_str = ["ER", "PGR", "HER2"]

    # Iterate for ER, PGR, and HER2
    for protein in range(3):
        # start timer
        start = timeit.default_timer()

        # Title
        print("\n" + temp_str[protein] + " Status Prediction\n")
        
        
        #########################
        #### PREPARE DATASET ####
        #########################
        # Split dataset into training and test set
        train_input_set, test_input_set, train_label_set, test_label_set = train_test_split(datasets[protein*2], datasets[(protein*2)+1], test_size=0.25, random_state=100)
        # Size of input layer
        _, nr_in = train_input_set.shape
        # Number of training batches
        n_train_batches = train_input_set.shape[0] // batch_size

        # cast inputs and labels as shared variable to accelerate computation
        train_set_x, train_set_y = shared_dataset(data_xy = (train_input_set,train_label_set))
        test_set_x, test_set_y = shared_dataset(data_xy = (test_input_set,test_label_set))

        
        #########################
        ##### BUILD NN MODEL ####
        #########################
        print('Build NN Model')
        numpy_rng = numpy.random.RandomState(123)
        if protein==2:
            # HER2 label dataset consist of 4 classes:
            # 'POSITIVE', 'NEGATIVE', 'EQUIVOCAL', 'INDETERMINATE'
            n_classes = 4
            class_names = ['Positive','Negative','Indeterminate','Equivocal']
            class_nr = [0,1,2,3]
            colors = cycle(['aqua', 'darkorange', 'cornflowerblue', 'deeppink'])
        else:
            # ER and PGR label dataset consist of 3 classes:
            # 'POSITIVE', 'NEGATIVE', 'INDETERMINATE'
            n_classes = 3
            class_names = ['Positive','Negative','Indeterminate']
            class_nr = [0,1,2]
            colors = cycle(['aqua', 'darkorange', 'cornflowerblue'])
        
        dbn = DBN(numpy_rng=numpy_rng, n_ins=nr_in, hidden_layers_sizes=layers, n_outs=n_classes)

        
        #########################
        ### PRETRAIN NN MODEL ###
        #########################
        print('Pretrain NN Model')
        
        # Get the pretraining functions. It is on the amount of the number of layers.
        pretraining_fns = dbn.pretraining_functions(train_set_x=train_set_x, batch_size=batch_size, k=k)

        # iterate for each RBMs
        for i in range(dbn.n_layers):
            # iterate for pretraining epochs
            for epoch in range(pretraining_epochs):
                c = []
                # iterate for number of training batches
                for batch_index in range(n_train_batches):
                    # c is a list of monitoring cost per batch for RBM[i]
                    c.append(pretraining_fns[i](index=batch_index, lr=pretrain_lr))

        
        #########################
        ### FINETUNE NN MODEL ###
        #########################
        print('Train NN Model')
        
        # Get the training functions.
        train_fn = dbn.build_finetune_functions(train_set_x=train_set_x, train_set_y=train_set_y, batch_size=batch_size, learning_rate=finetune_lr, dropout=dropout, optimizer=optimizer)

        # iterate for training epochs
        for j in range(training_epochs):
            # iterate for number of training batches
            for minibatch_index in range(n_train_batches):
                train_fn(minibatch_index)

        
        #########################
        ##### TEST NN MODEL #####
        #########################
        print('Test NN Model')
        
        # Get the test functions.
        test_model = dbn.predict(test_set_x=test_set_x, dropout=dropout)
        test_model_onehot = dbn.predict_onehot(test_set_x=test_set_x, dropout=dropout)
        
        # take the test result
        test_predicted_label_set = test_model()
        test_predicted_label_set_onehot = test_model_onehot()
        print(test_predicted_label_set_onehot)
        
        # accuracy, p, r, f, s
        accuracy = accuracy_score(test_label_set, test_predicted_label_set)
        p, r, f, s = precision_recall_fscore_support(test_label_set, test_predicted_label_set, average='weighted')

        # print results
        print("Accuracy = " + str(accuracy))
        print("Precision = " + str(p))
        print("Recall = " + str(r))
        print("F1-sscore = " + str(f))

        # confusion matrix
        cnf_matrix = confusion_matrix(test_label_set, test_predicted_label_set)
        
        plt.figure()
        print_and_plot_confusion_matrix(cnf_matrix, classes=class_names, normalize=False, title='Confusion matrix, without normalization')
        plt.show()

        # ROC curve
        fpr = dict()
        tpr = dict()
        roc_auc = dict()
        test_label_set_ = label_binarize(test_label_set, classes=class_nr)
        for i in range(n_classes):
            fpr[i], tpr[i], _ = roc_curve(test_label_set_[:, i], test_predicted_label_set_onehot[:, i])
            roc_auc[i] = auc(fpr[i], tpr[i])

        plt.figure()

        for i, color in zip(range(n_classes), colors):
            plt.plot(fpr[i], tpr[i], color=color, lw=2,
                     label='ROC curve of class {0} (area = {1:0.2f})'
                     ''.format(i, roc_auc[i]))

        plt.plot([0, 1], [0, 1], 'k--', lw=2)
        plt.xlim([0.0, 1.0])
        plt.ylim([0.0, 1.05])
        plt.xlabel('False Positive Rate')
        plt.ylabel('True Positive Rate')
        plt.legend(loc="lower right")
        plt.show()
        
        # stop timer and show result
        stop = timeit.default_timer()
        print(temp_str[protein] + " Status Prediction is done in " + str(stop-start) + "s")



if __name__ == '__main__':
    start = timeit.default_timer()

    print("\n\nWhat type of features do you want to use?")
    print("[1] DNA Methylation")
    print("[2] Gene Expression")
    print("[3] miRNA Expression")
    
    try:
        features = input("Insert here [default = 3]: ")
    except Exception as e:
        features = 3

    if features == 1:   # if DNA Methylation is picked
        print("You will use DNA Methylation data to create the prediction")
        print("\nWhat type DNA Methylation data do you want to use?")
        print("[1] Platform GPL8490\t(27578 cpg sites)")
        print("[2] Platform GPL16304\t(485577 cpg sites)")
        try:
            met = input("Insert here [default = 1]: ")
        except Exception as e:
            met = 1
        
        if met == 2: # if Platform GPL16304 is picked
            print("You will use DNA Methylation Platform GPL16304 data")
            DATASET = 2
        else:       # if Platform GPL8490 or any other number is picked
            print("You will use DNA Methylation Platform GPL8490 data")
            DATASET = 1
        
    elif features == 2: # if Gene Expression is picked
        print("You will use Gene Expression data to create the prediction")
        print("\nWhat type Gene Expression data do you want to use?")
        print("[1] Count")
        print("[2] FPKM")
        print("[3] FPKM-UQ")
        try:
            gen = input("Insert here [default = 1]: ")
        except Exception as e:
            gen = 1
        
        if gen == 2:    # if FPKM is picked
            print("You will use Gene Expression FPKM data")
            DATASET = 4
        elif gen == 3:  # if FPKM-UQ is picked
            print("You will use Gene Expression FPKM-UQ data")
            DATASET = 5
        else:           # if Count or any other number is picked
            print("You will use Gene Expression Count data")
            DATASET = 3
        
    else:   # if miRNA Expression or any other number is picked
        DATASET = 6
        print("You will use miRNA Expression data to create the prediction")

    test_DBN(dataset=DATASET)

    stop = timeit.default_timer()
    print(stop-start)