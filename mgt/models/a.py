from __future__ import annotations
from datetime import time

import time

import torch
import numpy as np

from block_recurrent_transformer_pytorch import BlockRecurrentTransformer

from mgt.datamanagers.data_manager import Dictionary
from mgt.models import utils


defaults = {
    'max_sequence_length': 512,
    'learning_rate': 1e-4,
    'dropout': 0.1,
    'dim': 512,
    'depth': 12,
    'heads': 8
}


class TransformerModel(object):

    def __init__(self,
                 dictionary: Dictionary,
                 max_sequence_length=defaults['max_sequence_length'],
                 learning_rate=defaults['learning_rate'],
                 dropout=defaults['dropout'],
                 dim=defaults['dim'],
                 depth=defaults['depth'],
                 heads=defaults['heads']
                 ):
        self.dictionary = dictionary
        self.learning_rate = learning_rate
        self.max_sequence_length = max_sequence_length
        self.dropout = dropout
        self.dim = dim
        self.depth = depth
        self.heads = heads
        self.model = self.create_model()
        self.optimizer = self.create_optimizer()

    def set_learning_rate(self, learning_rate):
        self.learning_rate = learning_rate
        self.optimizer = self.create_optimizer()

    def train(self, x_train, epochs, batch_size=4, stop_loss=None, batches_per_epoch=100, report_per_x_batches=20,
              gradient_accumulation_steps=1):
        self.model.train()
        start_time = time.time()
        for epoch in range(epochs):
            print(f"Training epoch {epoch + 1}.")

            epoch_losses = []
            batch_losses = []
            nr_of_batches_processed = 0
            for _ in range(batches_per_epoch):

                for _ in range(gradient_accumulation_steps):
                    batch = utils.get_batch(
                        x_train,
                        batch_size=batch_size,
                        max_sequence_length=self.max_sequence_length)

                    torch_batch = torch.tensor(batch).long().to(utils.get_device())

                    loss = self.model(torch_batch)
                    loss.backward()

                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 0.5)
                self.optimizer.step()
                self.optimizer.zero_grad()

                nr_of_batches_processed += 1

                loss_item = loss.item()

                batch_losses.append(loss_item)
                epoch_losses.append(loss_item)

                if nr_of_batches_processed % report_per_x_batches == 0:
                    print(
                        f"Processed {nr_of_batches_processed} / {batches_per_epoch} with loss {np.mean(batch_losses)}.")
                    batch_losses = []

            epoch_loss = np.mean(epoch_losses)
            if stop_loss is not None and epoch_loss <= stop_loss:
                print(f"Loss of {epoch_loss} was lower than stop loss of {stop_loss}. Stopping training.")
                return

            running_time = (time.time() - start_time)
            print(f"Loss after epoch {epoch + 1} is {epoch_loss}. Running time: {running_time}")

    def generate(self, output_length=100, temperature=1., filter_treshold=0.9, prompt=None):
        print(f"Generating a new song with {output_length} characters.")
        if prompt is None:
            prompt = [0]

        self.model.eval()
        initial = torch.tensor([prompt]).long().to(utils.get_device())  # assume 0 is start token

        sample = self.model.generate(initial, output_length, temperature=temperature, filter_thres=filter_treshold)
        return sample.cpu().detach().numpy()[0]

    def create_model(self):
        model = BlockRecurrentTransformer(
          num_tokens = self.dictionary.size(),             # vocab size
          dim = 512,                      # model dimensions
          depth = 6,                      # depth
          dim_head = 64,                  # attention head dimensions
          heads = 8,                      # number of attention heads
          max_seq_len = self.max_sequence_length,             # the total receptive field of the transformer, in the paper this was 2 * block size
          block_width = 512,              # block size - total receptive field is max_seq_len, 2 * block size in paper. the block furthest forwards becomes the new cached xl memories, which is a block size of 1 (please open an issue if i am wrong)
          xl_memories_layers = (5, 6),    # which layers to use xl memories. very old deepmind papers have shown you only need the last penultimate layers to have cached key values to see majority of benefit
          num_state_vectors = 512,        # number of state vectors, i believe this was a single block size in the paper, but can be any amount
          recurrent_layers = (4,),        # where to place the recurrent layer(s) for states with fixed simple gating
          enhanced_recurrence = True      # enhanced recurrence from ernie-doc paper, i have seen it to work well on my local machine
          ).to(utils.get_device())
        model = RecurrentTrainerWrapper(model,xl_memories_dropout = 0.1,state_dropout = 0.1,).to(utils.get_device())
        return model

    def create_optimizer(self):
        return torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)

    def save_checkpoint(self, path):
        print(f'Saving checkpoint {path}')
        torch.save({
            'dictionary': self.dictionary,
            'max_sequence_length': self.max_sequence_length,
            'learning_rate': self.learning_rate,
            'dropout': self.dropout,
            'dim': self.dim,
            'depth': self.depth,
            'heads': self.heads,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
        }, path)

    @staticmethod
    def load_checkpoint(path) -> TransformerModel:
        checkpoint = torch.load(path)
        model = TransformerModel(
            dictionary=checkpoint['dictionary'],
            max_sequence_length=utils.get_or_default(checkpoint, 'max_sequence_length', defaults),
            learning_rate=utils.get_or_default(checkpoint, 'learning_rate', defaults),
            dropout=utils.get_or_default(checkpoint, 'dropout', defaults),
            dim=utils.get_or_default(checkpoint, 'dim', defaults),
            depth=utils.get_or_default(checkpoint, 'depth', defaults),
            heads=utils.get_or_default(checkpoint, 'heads', defaults)
        )

        model.model.load_state_dict(checkpoint['model_state_dict'], strict=False)

        return model
