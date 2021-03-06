import tensorflow as tf
import numpy as np
from . import utils
import json

# Reference: https://github.com/MorvanZhou/Reinforcement-learning-with-tensorflow/blob/master/contents/7_Policy_gradient_softmax/RL_brain.py
save_file_name = "savefile.ckpt"
parameters_file_name = "paras.json"
gpu_usage_w_limit = True
loaded_models = {
	
}

class PolicyGradient:
	def __init__(self, from_save = None, n_inputs = None, n_actions = None, hidden_layers = None, learning_rate = 0.01, reward_decay = 0.95):
		self.__ep_obs, self.__ep_as, self.__ep_rs = [], [], []

		self.__graph = tf.Graph()
		self.__config = tf.ConfigProto(**utils.parallel_parameters)
		if gpu_usage_w_limit:
			self.__config.gpu_options.allow_growth = True
			self.__config.gpu_options.per_process_gpu_memory_fraction = 0.5

		self.__sess = tf.Session(graph = self.__graph, config = self.__config)
		with self.__graph.as_default() as g:
			if from_save is None:
				self.__build_graph(n_inputs, n_actions, hidden_layers, learning_rate)
				self.__reward_decay = reward_decay
				self.__sess.run(tf.global_variables_initializer())
				self.__learn_step_counter = 0
				self.__n_actions = n_actions
			else:
				with open(from_save.rstrip("/") + "/" + parameters_file_name, "r") as f:
					paras_dict = json.load(f)
				
				for key, value in paras_dict.items():
					self.__dict__["_%s%s"%(self.__class__.__name__, key)] = value

				saver = tf.train.import_meta_graph(from_save.rstrip("/") + "/" + save_file_name + ".meta")
				saver.restore(self.__sess, from_save.rstrip("/") + "/" + save_file_name)
				self.__obs = g.get_tensor_by_name("observations:0")
				self.__acts = g.get_tensor_by_name("actions_num:0")
				self.__vt = g.get_tensor_by_name("actions_value:0")

				self.__all_act_prob = tf.get_collection("all_act_prob")[0]
				self.__loss = tf.get_collection("loss")[0]
				self.__train__op = tf.get_collection("train_op")[0]

	def __build_graph(self, n_inputs, n_actions, hidden_layers, learning_rate):
		def add_dense_layers(inputs, hidden_layers, activation = tf.nn.relu, act_apply_last = False):
			prev_layer = inputs
			for n_neurons in hidden_layers[0:len(hidden_layers) - 1]:
				prev_layer = tf.layers.dense(inputs = prev_layer, units = n_neurons, activation = activation)

			if len(hidden_layers) > 0:
				prev_layer = tf.layers.dense(inputs = prev_layer, units = hidden_layers[len(hidden_layers) - 1], activation = activation if act_apply_last else None)
			
			return prev_layer

		with tf.name_scope('inputs'):
			self.__obs = tf.placeholder(tf.float32, [None, n_inputs], name = "observations")
			self.__acts = tf.placeholder(tf.int32, [None, ], name = "actions_num")
			self.__vt = tf.placeholder(tf.float32, [None, ], name = "actions_value")
	
		result = add_dense_layers(self.__obs, hidden_layers + [n_actions])

		self.__all_act_prob = tf.nn.softmax(result, name = 'act_prob')  # use softmax to convert to probability

		with tf.name_scope('loss'):
			# to maximize total reward (log_p * R) is to minimize -(log_p * R), and the tf only have minimize(loss)
			neg_log_prob = tf.nn.sparse_softmax_cross_entropy_with_logits(logits = result, labels = self.__acts)   # this is negative log of chosen action
			self.__loss = tf.reduce_mean(neg_log_prob * self.__vt)  # reward guided loss

		with tf.name_scope('train'):
			self.__train_op = tf.train.AdamOptimizer(learning_rate).minimize(self.__loss)

		tf.add_to_collection("all_act_prob", self.__all_act_prob)
		tf.add_to_collection("loss", self.__loss)
		tf.add_to_collection("train_op", self.__train_op)

	@property 
	def learn_step_counter(self):
		return self.__learn_step_counter

	def choose_action(self, observation, action_filter = None, return_value = False):

		if action_filter is None:
			action_filter = np.full(self.__n_actions, 1.0)

		n_actions_avail = np.sum(action_filter > 0)
		prob_weights = self.__sess.run(
			self.__all_act_prob, 
			feed_dict = {
				self.__obs: observation[np.newaxis, :]
			})

		prob_weights = np.multiply(prob_weights, action_filter)
		overall = prob_weights.sum(axis = 1)

		zero_prob_entries = np.where(overall < 1e-6)[0]
		if zero_prob_entries.shape[0] > 0:
			action_indices = np.where(action_filter > 0)[0]
			prob_weights[zero_prob_entries, action_indices] = 1.0/n_actions_avail
			overall = prob_weights.sum(axis = 1)
		
		prob_weights /= overall[:, np.newaxis]
		action = np.random.choice(range(prob_weights.shape[1]), p = prob_weights.ravel())  # select action w.r.t the actions prob
		value = prob_weights[:, action]

		if return_value:
			return action, return_value

		return action

	def store_transition(self, state, action, reward):
		self.__ep_obs.append(state)
		self.__ep_as.append(action)
		self.__ep_rs.append(reward)

	def learn(self, display_cost = True):
		def discount_and_norm_rewards():
			# discount episode rewards
			discounted_ep_rs = np.zeros_like(self.__ep_rs, dtype = np.float32)

			running_add = 0
			for t in reversed(range(0, len(self.__ep_rs))):
				running_add = running_add * self.__reward_decay + self.__ep_rs[t]
				discounted_ep_rs[t] = running_add

			# normalize episode rewards
			discounted_ep_rs -= np.mean(discounted_ep_rs)
			std = np.std(discounted_ep_rs)
			if std >= 1e-3:
				discounted_ep_rs /= std
			return discounted_ep_rs


		# discount and normalize episode reward
		discounted_ep_rs_norm = discount_and_norm_rewards()

		# train on episode
		_, loss = self.__sess.run(
			[self.__train_op, self.__loss], 
			feed_dict={
				self.__obs: np.stack(self.__ep_obs, axis = 0),
				self.__acts: np.array(self.__ep_as),
				self.__vt: discounted_ep_rs_norm
			}
		)

		self.__ep_obs, self.__ep_as, self.__ep_rs = [], [], []
		if display_cost:
			print("#%4d: %.4f"%(self.__learn_step_counter + 1, loss))
		self.__learn_step_counter += 1

		return loss

	def save(self, save_dir):
		paras_dict = {
			"__reward_decay": self.__reward_decay,
			"__learn_step_counter": self.__learn_step_counter,
			"__n_actions": self.__n_actions
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