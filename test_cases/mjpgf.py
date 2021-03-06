'''
This experiment trains the policy gradient model by forcing it to follow moves given by heuristic players.
'''
import argparse
import numpy as np
import random
import signal
from MLUtils import get_MJPGFitted
import Player, Game
import MoveGenerator
from . import utils

EXIT_FLAG = False
names = ["Amy", "Billy", "Clark", "David"]
model_flag = "pgf"
freq_shuffle_players = 8
freq_model_save = None
game_record_size = 100
game_record_count = 0

game_record = np.zeros((game_record_size, 4, 2))

pg_model_paras = {
	"learning_rate": 1e-3,
	"reward_decay": 0.99,
	"sl_memory_size": 800,
	"sl_batch_size": 200,
	"n_actions": 48 if model_flag == "pgf" else 39,
	"rnn_net": False
}

pg_model_path = "test"

trainer_conf = [model_flag, model_flag, model_flag]

trainer_models = {
	"heuristics": {
		"class": MoveGenerator.RuleBasedAINaive,
		"parameters":{
			 "display_step": False,
			 "s_chow": 2,
			 "s_pong": 6,
			 "s_future": 1,
			 "s_explore": 0,
			 "s_neighbor_suit": 0,
			 "s_mixed_suit": 0
		}
	},
	"pgf": {
		"class": MoveGenerator.PGFGenerator,
		"parameters": {
			"display_step": False,
			"is_train": False,
			"skip_history": False,
			"pg_model_path": pg_model_path
		}
	},
	"pgfr": {
		"class": MoveGenerator.PGFRGenerator,
		"parameters": {
			"display_step": False,
			"is_train": False,
			"skip_history": False,
			"pg_model_path": pg_model_path
		}
	},
	"random": {
		"class": MoveGenerator.RandomGenerator,
		"parameters":{
			"display_step": False
		}
	}
}

def signal_handler(signal, frame):
	global EXIT_FLAG
	print("Signal received, cleaning up..")
	EXIT_FLAG = True

def parse_args(args_list):
	parser = argparse.ArgumentParser()
	parser.add_argument("--model_dir", type = str, help = "Where is the model")
	parser.add_argument("action", type = str, choices = ["train", "test", "play"], help = "What to do with the model")
	parser.add_argument("n_episodes", nargs = "?", default = 1, type = int, help = "No. of episodes to go through")
	parser.add_argument("save_name", nargs = "?", default = None, type = str, help = "Path to save the model")
	args = parser.parse_args(args_list)
	return args

def test(args):
	global game_record_count
	args = parse_args(args)

	if args.action == "train":
		if args.save_name is None:
			response = input("You have not entered save_name, are you sure? [y/n] ").lower()
			if response != "y":
				exit(-1)
		
		if args.model_dir is None:
			args.model_dir = pg_model_path
		else:
			trainer_models["pgf"]["parameters"]["pg_model_path"] = args.model_dir
			trainer_models["pgfr"]["parameters"]["pg_model_path"] = args.model_dir
		
		freq_model_save = args.n_episodes//10

	elif args.action in ["test", "play"]:
		if args.model_dir is None:
			raise Exception("model_dir must be given to test/play")

	model = get_MJPGFitted(args.model_dir, **pg_model_paras)

	players = []
	i = 0
	for model_tag in trainer_conf:
		if args.action == "play":
			player = Player.Player(MoveGenerator.Human, player_name = names[i])
		else:
			player = Player.Player(trainer_models[model_tag]["class"], player_name = names[i], **trainer_models[model_tag]["parameters"])
		players.append(player)
		i += 1

	pg_player = Player.Player(MoveGenerator.PGFGenerator if model_flag == "pgf" else MoveGenerator.PGFRGenerator , player_name = names[i], pg_model_path = args.model_dir, skip_history = False, is_train = args.action == "train", display_step = args.action == "play")
	players.append(pg_player)

	if args.action != "play":
		signal.signal(signal.SIGINT, signal_handler)
	game, shuffled_players, last_saved = None, None, -1
	for i in range(args.n_episodes):
		if EXIT_FLAG:
			break

		if i % freq_shuffle_players == 0:
			shuffled_players =  random.sample(players, k = 4)
			game = Game.Game(shuffled_players)

		winner, losers, penalty = game.start_game()
		if args.action == "train":
			model.learn(display_cost = (i+1) % game_record_size == 0)
		
		index = game_record_count%game_record_size
		game_record[index, :, :] = np.zeros((4, 2))
		game_record_count += 1

		if winner is not None:
			winner_id = players.index(winner)
			game_record[index, winner_id, 0] = 1
			for loser in losers:
				loser_id = players.index(loser)
				game_record[index, loser_id, 1] = 1

		if (i+1) % game_record_size == 0:
			print("#%5d: %.2f%%/%.2f%%\t%.2f%%/%.2f%%\t%.2f%%/%.2f%%\t%.2f%%/%.2f%%"%(i+1, game_record[:, 0, 0].mean()* 100, game_record[:, 0, 1].mean()* 100,
																							game_record[:, 1, 0].mean()* 100, game_record[:, 1, 1].mean()* 100, 
																							game_record[:, 2, 0].mean()* 100, game_record[:, 2, 1].mean()* 100, 
																							game_record[:, 3, 0].mean()* 100, game_record[:, 3, 1].mean()* 100))
		'''
		if args.action == "train" and args.save_name is not None and (i+1) % freq_model_save == 0:
			last_saved = i
			path = args.save_name.rstrip("/") + "_%d"%(i + 1)
			utils.makesure_dir_exists(path)
			model.save(path)
		'''

	if args.action == "train" and args.save_name is not None:
		if last_saved < args.n_episodes - 1:
			path = args.save_name.rstrip("/") + "_%d"%args.n_episodes
			utils.makesure_dir_exists(path)
			model.save(path)
