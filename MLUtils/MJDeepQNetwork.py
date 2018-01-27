from .AbstractDNN import AbstractDNN
from . import utils
import tensorflow as tf
import random
import numpy as np
import json

save_file_name = "savefile.ckpt"
parameters_file_name = "paras.json"
gpu_usage_w_limit = True
loaded_models = {
	
}

n_actions = 42
sample_shape = [9, 34, 1]
def get_MJDeepQNetwork(path, **kwargs):
	if path not in loaded_models:
		try:
			loaded_models[path] = MJDeepQNetwork.load(from_save = path)
		except:
			loaded_models[path] = MJDeepQNetwork(**kwargs)
	return loaded_models[path]


# Reference:
# https://github.com/MorvanZhou/Reinforcement-learning-with-tensorflow/blob/master/contents/5_Deep_Q_Network/DQN_modified.py

class MJDeepQNetwork:
	def __init__(self, from_save = None, learning_rate = 1e-2, reward_decay = 0.9, e_greedy = 0.9, dropout_rate = 0.1, replace_target_iter = 300, memory_size = 500, batch_size = 100):
		self.__graph = tf.Graph()
		self.__config = tf.ConfigProto(**utils.parallel_parameters)
		if gpu_usage_w_limit:
			self.__config.gpu_options.allow_growth = True
			self.__config.gpu_options.per_process_gpu_memory_fraction = 0.5

		self.__sess = tf.Session(graph = self.__graph, config = self.__config)
		with self.__graph.as_default() as g:
			if from_save is None:
				if type(n_inputs) != int or type(n_actions) != int:
					raise Exception("n_input and n_actions must be integers")
				self.__epsilon = e_greedy
				self.__memory_size = memory_size
				self.__replace_target_iter = replace_target_iter
				self.__batch_size = batch_size
				self.__learn_step_counter = 0

				self.__build_graph(learning_rate, reward_decay, dropout_rate)
				self.__sess.run(tf.global_variables_initializer())
			else:
				with open(from_save.rstrip("/") + "/" + parameters_file_name, "r") as f:
					paras_dict = json.load(f)
				
				for key, value in paras_dict.items():
					self.__dict__["_%s%s"%(self.__class__.__name__, key)] = value
				
				saver = tf.train.import_meta_graph(from_save.rstrip("/") + "/" + save_file_name + ".meta")
				saver.restore(self.__sess, from_save.rstrip("/") + "/" + save_file_name)
				self.__s = g.get_tensor_by_name("s:0")
				self.__s_ = g.get_tensor_by_name("s_:0")
				self.__r = g.get_tensor_by_name("r:0")
				self.__a = g.get_tensor_by_name("a:0")
				self.__is_train = g.get_tensor_by_name("is_train:0")
				self.__q_eval = tf.get_collection("q_eval")[0]
				self.__loss = tf.get_collection("loss")[0]
				self.__train__op = tf.get_collection("train_op")[0]
				self.__target_replace_op = tf.get_collection("target_replace_op")

			self.__memory_counter = 0
			self.__memory = np.zeros((self.__memory_size, self.__n_inputs * 2 + 2))

		tf.reset_default_graph()

	def __build_graph(self, learning_rate, reward_decay, dropout_rate):
		def make_connection(inputs, is_train, dropout_rate):
			# 9*34*8
			conv_1 = tf.layers.conv2d(inputs = inputs, filters = 8, kernel_size = [1, 3], padding = "same", activation = tf.nn.relu)
			# 1*32*16
			conv_2 = tf.layers.conv2d(inputs = conv_1, filters = 16, kernel_size = [sample_shape[0], 3], padding = "valid", activation = tf.nn.relu)
			
			flat = tf.reshape(conv_2, [-1, 32*16])
			dense = tf.layers.dense(inputs = flat, units = 2048, activation = tf.nn.relu)
			dropout = tf.layers.dropout(inputs = dense, rate = dropout_rate, training = is_train)
			return tf.layers.dense(inputs = dropout, units = n_actions)

		self.__s = tf.placeholder(tf.float32, [None] + sample_shape, name = "s")
		self.__s_ = tf.placeholder(tf.float32, [None] + sample_shape, name = "s_")
		self.__r = tf.placeholder(tf.float32, [None, ], name = "r")
		self.__a = tf.placeholder(tf.int32, [None, ], name = "a")
		self.__is_train = tf.placeholder(tf.bool, [], name = "is_train") 
		
		with tf.variable_scope("eval_net"):
			self.__q_eval = make_connection(self.__s, self.__is_train, dropout_rate)

		with tf.variable_scope("target_net"):
			self.__q_next = make_connection(self.__s_, self.__is_train, dropout_rate)

		self.__q_target = tf.stop_gradient(self.__r + reward_decay * tf.reduce_max(self.__q_next, axis = 1))
		
		a_indices = tf.stack([tf.range(tf.shape(self.__a)[0], dtype = tf.int32), self.__a], axis=1)
		self.__q_eval_wrt_a = tf.gather_nd(params = self.__q_eval, indices = a_indices)
		
		self.__loss = tf.reduce_mean(tf.squared_difference(self.__q_target, self.__q_eval_wrt_a), name = "TD_error")
		self.__train__op = tf.train.RMSPropOptimizer(learning_rate).minimize(self.__loss)

		eval_net_params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='eval_net')
		target_net_params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope='target_net')
		self.__target_replace_op = [tf.assign(t, e) for t, e in zip(target_net_params, eval_net_params)]

		tf.add_to_collection("q_eval", self.__q_eval)
		tf.add_to_collection("loss", self.__loss)
		tf.add_to_collection("train_op", self.__train__op)
		for op in self.__target_replace_op:
			tf.add_to_collection("target_replace_op", op)

	@property 
	def learn_step_counter(self):
		return self.__learn_step_counter

	def store_transition(self, state, action, reward, state_):
		transition = np.hstack((state, [action, reward], state_))
		index = self.__memory_counter % self.__memory_size
		self.__memory[index, :] = transition
		self.__memory_counter += 1

	def choose_action(self, state, valid_actions = None, eps_greedy = True):
		if np.random.uniform() < self.__epsilon or not eps_greedy:
			inputs = state[np.newaxis, :]
			with self.__graph.as_default() as g:
				actions_value = self.__sess.run(self.__q_eval, feed_dict = {self.__s: inputs, self.__is_train: False})
			tf.reset_default_graph()
			if valid_actions is not None:
				action = valid_actions[np.argmax(actions_value[:, valid_actions])]
			else:
				action = np.argmax(actions_value)
		else:
			if valid_actions is not None:
				action = random.choice(valid_actions)
			else:
				action = random.choice(list(range(n_actions)))

		return action

	def learn(self, display_cost = True):
		if self.__learn_step_counter % self.__replace_target_iter == 0:
			self.__sess.run(self.__target_replace_op)
			#print("#%4d: Replaced target network"%(self.__learn_step_counter))

		sample_index = np.random.choice(min(self.__memory_size, self.__batch_size), size = self.__batch_size)
		batch_memory = self.__memory[sample_index, :]
		with self.__graph.as_default() as g:
			_, cost = self.__sess.run(
				[self.__train__op, self.__loss],
				feed_dict = {
					self.__s: batch_memory[:, :self.__n_inputs],
					self.__a: batch_memory[:, self.__n_inputs],
					self.__r: batch_memory[:, self.__n_inputs + 1],
					self.__s_: batch_memory[:, -self.__n_inputs:],
					self.__is_train: True
				})
		tf.reset_default_graph()
		if display_cost:
			print("#%4d: %.4f"%(self.__learn_step_counter + 1, cost))

		self.__learn_step_counter += 1

	def save(self, save_dir):
		paras_dict = {
			"__n_actions": self.__n_actions,
			"__n_inputs": self.__n_inputs,
			"__epsilon": self.__epsilon,
			"__memory_size": self.__memory_size,
			"__replace_target_iter": self.__replace_target_iter,
			"__batch_size": self.__batch_size,
			"__learn_step_counter": self.__learn_step_counter,
			"__dropout_rate": self.__dropout_rate
		}
		with open(save_dir.rstrip("/") + "/" + parameters_file_name, "w") as f:
			json.dump(paras_dict, f, indent = 4)

		with self.__graph.as_default() as g:
			saver = tf.train.Saver()
			save_path = saver.save(self.__sess, save_path = save_dir.rstrip("/")+"/"+save_file_name)
		tf.reset_default_graph()

	@classmethod
	def load(cls, path):
		model = cls(from_save = path)
		return model