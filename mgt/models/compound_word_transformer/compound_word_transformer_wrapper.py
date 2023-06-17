################################################################################
# Sampling
################################################################################
# -- temperature -- #
import numpy as np
import torch
from torch import nn
from x_transformers.x_transformers import AttentionLayers, default, AbsolutePositionalEmbedding, always

from mgt.models.compound_word_transformer.compound_transformer_embeddings import CompoundTransformerEmbeddings
from mgt.models.utils import get_device
from einops import rearrange, repeat
import itertools
import math
from einops import rearrange, reduce, repeat

def tiv(q):
    c = [0]*6*2
    c = np.array(c)
    count = 0
    for i in q:
        a = [math.sin(math.radians(30*-i)),math.cos(math.radians(30*-i)),math.sin(math.radians(60*-i)),math.cos(math.radians(60*-i)),math.sin(math.radians(90*-i)),math.cos(math.radians(90*-i)),math.sin(math.radians(120*-i)),math.cos(math.radians(120*-i)),math.sin(math.radians(150*-i)),math.cos(math.radians(150*-i)),math.sin(math.radians(180*-i)),math.cos(math.radians(180*-i))]
        a = np.array(a)
        c = c + a
        count += 1
    if count != 0:
        c /= count
    a = 0
    for i in c:
        a = a + i * i
        a = math.sqrt(a)
    return a

def notes_to_ce(indices):
  note_index_to_pitch_index = [0, -5, 2, -3, 4, -1, -6, 1, -4, 3, -2, 5]
  total = np.zeros(3)
  count = 0
  for index in indices:
    total += pitch_index_to_position(note_index_to_pitch_index[index])
    count += 1
  if count != 0:
    total /= count               
  return total.tolist()    

def pitch_index_to_position(pitch_index) :
    c = pitch_index - (4 * (pitch_index // 4))
    verticalStep = 0.4
    radius = 1.0
    pos = np.array([0.0, 0.0, 0.0])
    if c == 0:
        pos[1] = radius
    if c == 1:
        pos[0] = radius
    if c == 2:
        pos[1] = -1*radius
    if c == 3:
        pos[0] = -1*radius
    pos[2] = pitch_index * verticalStep
    return np.array(pos)

def largest_distance(pitches):
    if len(pitches) < 2:
        return 0
    diameter = 0
    pitch_pairs = itertools.combinations(pitches, 2)
    for pitch_pair in pitch_pairs:
        distance = np.linalg.norm(pitch_index_to_position(
            pitch_pair[0]) - pitch_index_to_position(pitch_pair[1]))
        if distance > diameter:
            diameter = distance
    return diameter

def softmax_with_temperature(logits, temperature):
    probs = np.exp(logits / temperature) / np.sum(np.exp(logits / temperature))
    return probs

def weighted_sampling(probs):
    probs /= sum(probs)
    sorted_probs = np.sort(probs)[::-1]
    sorted_index = np.argsort(probs)[::-1]
    word = np.random.choice(sorted_index, size=1, p=sorted_probs)[0]
    return word

# -- nucleus -- #
def nucleus(probs, probability_treshold):
    probs /= (sum(probs) + 1e-5)
    sorted_probs = np.sort(probs)[::-1]
    sorted_index = np.argsort(probs)[::-1]
    cusum_sorted_probs = np.cumsum(sorted_probs)
    after_threshold = cusum_sorted_probs > probability_treshold
    if sum(after_threshold) > 0:
        last_index = np.where(after_threshold)[0][0] + 1
        candi_index = sorted_index[:last_index]
    else:
        candi_index = sorted_index[:]
    candi_probs = [probs[i] for i in candi_index]
    candi_probs /= sum(candi_probs)
    word = np.random.choice(candi_index, size=1, p=candi_probs)[0]
    return word

def sampling(logit, probability_treshold=None, temperature=1.0):
    logit = logit.squeeze().cpu().detach().numpy()
    probs = softmax_with_temperature(logits=logit, temperature=temperature)

    if probability_treshold is not None:
        cur_word = nucleus(probs, probability_treshold=probability_treshold)
    else:
        cur_word = weighted_sampling(probs)
    return cur_word

class CompoundWordTransformerWrapper(nn.Module):
    def __init__(
            self,
            *,
            num_tokens,
            max_seq_len,
            attn_layers,
            attn_layers1,
            emb_dim=None,
            emb_dropout=0.,
            use_pos_emb=True,
            emb_sizes=None
    ):
        super().__init__()
        assert isinstance(attn_layers, AttentionLayers), 'attention layers must be one of Encoder or Decoder'

        if emb_sizes is None:
            emb_sizes = [
                96,  # Bar / Beat
                512,  # Tempo
                512,  # Instrument
                512,  # Note Name
                512,  # Octave
                512,
                512
            ]

        self.emb_sizes = emb_sizes

        dim = attn_layers.dim
        emb_dim = default(emb_dim, dim)

        self.num_tokens = num_tokens
        self.max_seq_len = max_seq_len

        self.word_emb_type = CompoundTransformerEmbeddings(self.num_tokens[0], self.emb_sizes[0])
        self.word_emb_barbeat = CompoundTransformerEmbeddings(self.num_tokens[1], self.emb_sizes[1])
        self.word_emb_tempo = CompoundTransformerEmbeddings(self.num_tokens[2], self.emb_sizes[2])
        self.word_emb_instrument = CompoundTransformerEmbeddings(self.num_tokens[3], self.emb_sizes[3])
        self.word_emb_note_name = CompoundTransformerEmbeddings(self.num_tokens[4], self.emb_sizes[4])
        self.word_emb_octave = CompoundTransformerEmbeddings(self.num_tokens[5], self.emb_sizes[5])
        self.word_emb_duration = CompoundTransformerEmbeddings(self.num_tokens[6], self.emb_sizes[6])
        
        # individual output
        self.word_emb_type = CompoundTransformerEmbeddings(self.num_tokens[0], self.emb_sizes[0])
        self.word_emb_barbeat = CompoundTransformerEmbeddings(self.num_tokens[1], self.emb_sizes[1])
        self.word_emb_tempo = CompoundTransformerEmbeddings(self.num_tokens[2], self.emb_sizes[2])
        self.word_emb_instrument = CompoundTransformerEmbeddings(self.num_tokens[3], self.emb_sizes[3])
        self.word_emb_note_name = CompoundTransformerEmbeddings(self.num_tokens[4], self.emb_sizes[4])
        self.word_emb_octave = CompoundTransformerEmbeddings(self.num_tokens[5], self.emb_sizes[5])
        self.word_emb_duration = CompoundTransformerEmbeddings(self.num_tokens[6], self.emb_sizes[6])
        
        # individual output
        self.proj_type = nn.Sequential(
            nn.Linear(dim, self.num_tokens[0])
        )
        
        self.proj_barbeat = nn.Sequential(
            nn.Linear(dim, self.num_tokens[1])
        )
        
        self.proj_tempo = nn.Sequential(
            nn.Linear(dim, self.num_tokens[2])
        )
        
        self.proj_instrument = nn.Sequential(
            nn.Linear(dim, self.num_tokens[3])
        )
        
        self.proj_note_name = nn.Sequential(
            nn.Linear(dim, self.num_tokens[4])
        )
        
        self.proj_octave = nn.Sequential(
            nn.Linear(dim, self.num_tokens[5])
        )
        
        self.proj_duration = nn.Sequential(
            nn.Linear(dim, self.num_tokens[6])
        )
        
        # in_features is equal to dimension plus dimensions of the type embedding

        self.compound_word_embedding_size = np.sum(emb_sizes)

        self.pos_emb = AbsolutePositionalEmbedding(self.compound_word_embedding_size, max_seq_len) 
        
        self.emb_dropout = nn.Dropout(emb_dropout)

        self.project_emb = nn.Linear(emb_dim, dim) if emb_dim != dim else nn.Identity()
        
        self.attn_layers = attn_layers
        self.attn_layers1 = attn_layers1
        
        self.pos_emb1 = AbsolutePositionalEmbedding(self.compound_word_embedding_size, 16) 
        
        self.start_token = nn.Parameter(torch.randn(512))
        
        self.norm = nn.LayerNorm(512)
        
        self.in_linear1 = nn.Linear(512*6 + 96, 512)
        
        self.in_linear8 = nn.Linear(512+5, 512)
       
        self.init_()

    def init_(self):
        nn.init.normal_(self.word_emb_type.weight(), std=0.02)
        nn.init.normal_(self.word_emb_barbeat.weight(), std=0.02)
        nn.init.normal_(self.word_emb_tempo.weight(), std=0.02)
        nn.init.normal_(self.word_emb_instrument.weight(), std=0.02)
        nn.init.normal_(self.word_emb_note_name.weight(), std=0.02)
        nn.init.normal_(self.word_emb_octave.weight(), std=0.02)
        nn.init.normal_(self.word_emb_duration.weight(), std=0.02)
        
    def reparameterize(self, mu, logvar, use_sampling=True, sampling_var=1.):
        std = torch.exp(0.5 * logvar).to(mu.device)
        if use_sampling:
            eps = torch.randn_like(std).to(mu.device) * sampling_var
        else:
            eps = torch.zeros_like(std).to(mu.device)
        return eps * std + mu
        

    def forward_output_sampling(self, h, selection_temperatures=None, selection_probability_tresholds=None):
        # sample type
        if selection_probability_tresholds is None:
            selection_probability_tresholds = {}

        if selection_temperatures is None:
            selection_temperatures = {}

        # project other
        proj_type = self.proj_type(h)
        proj_barbeat = self.proj_barbeat(h)
        proj_tempo = self.proj_tempo(h)
        proj_instrument = self.proj_instrument(h)
        proj_note_name = self.proj_note_name(h)
        proj_octave = self.proj_octave(h)
        proj_duration = self.proj_duration(h)
        
        # sampling gen_cond
        cur_word_type = sampling(
            proj_type,
            probability_treshold=selection_probability_tresholds.get(0, None),
            temperature=selection_temperatures.get(0, 1.0))
        
        cur_word_barbeat = sampling(
            proj_barbeat,
            probability_treshold=selection_probability_tresholds.get(1, None),
            temperature=selection_temperatures.get(1, 1.0))

        cur_word_tempo = sampling(
            proj_tempo,
            probability_treshold=selection_probability_tresholds.get(2, None),
            temperature=selection_temperatures.get(2, 1.0))

        cur_word_instrument = sampling(
            proj_instrument,
            probability_treshold=selection_probability_tresholds.get(3, None),
            temperature=selection_temperatures.get(3, 1.0))

        cur_word_note_name = sampling(
            proj_note_name,
            probability_treshold=selection_probability_tresholds.get(4, None),
            temperature=selection_temperatures.get(4, 1.0))

        cur_word_octave = sampling(
            proj_octave,
            probability_treshold=selection_probability_tresholds.get(5, None),
            temperature=selection_temperatures.get(5, 1.0))

        cur_word_duration = sampling(
            proj_duration,
            probability_treshold=selection_probability_tresholds.get(6, None),
            temperature=selection_temperatures.get(6, 1.0))


        dic = {(i, j, k): index for index, (i, j, k) in enumerate((i, j, k) for j in range(9) for i in range(12) for k in range(64))}
        inverse_dic = {v: k for k, v in dic.items()}
        q1 = []
        if cur_word_barbeat != 0 and cur_word_barbeat != 6913:
            q1.append(inverse_dic[cur_word_barbeat-1][0])
        if cur_word_tempo != 0 and cur_word_tempo != 6913:
            q1.append(inverse_dic[cur_word_tempo-1][0])
        if cur_word_instrument  != 0 and cur_word_instrument  != 6913:
            q1.append(inverse_dic[cur_word_instrument-1][0])
        if cur_word_note_name != 0 and cur_word_note_name != 6913:
            q1.append(inverse_dic[cur_word_note_name-1][0])
        if cur_word_octave != 0 and cur_word_octave != 6913:
            q1.append(inverse_dic[cur_word_octave-1][0])
        if cur_word_duration != 0 and cur_word_duration != 6913:
            q1.append(inverse_dic[cur_word_duration-1][0])

        
        # collect
        next_arr = np.array([
            cur_word_type,
            cur_word_barbeat,
            cur_word_tempo,
            cur_word_instrument,
            cur_word_note_name,
            cur_word_octave,
            cur_word_duration,
            notes_to_ce(q1)[0],
            notes_to_ce(q1)[1],
            notes_to_ce(q1)[2],
            largest_distance(q1),
            tiv(q1)
        ])
        return next_arr

    def forward_output(self,
                       h
                       ):

        proj_type = self.proj_type(h)
        proj_barbeat = self.proj_barbeat(h)
        proj_barbeat = self.proj_barbeat(h)
        proj_tempo = self.proj_tempo(h)
        proj_instrument = self.proj_instrument(h)
        proj_note_name = self.proj_note_name(h)
        proj_octave = self.proj_octave(h)
        
        return proj_type, proj_barbeat, proj_tempo, proj_instrument, proj_note_name, proj_octave

    def forward_hidden(
            self,
            x,
            mask=None,
            **kwargs
    ):

        mask = x[..., 0].bool()
        rand = torch.randn(x[..., 0].shape, device = x.device)
        rand[:, 0] = -torch.finfo(rand.dtype).max 
        num_mask = min(int(x[..., 0].shape[1] * 0.15), x[..., 0].shape[1] - 1)
        indices = rand.topk(num_mask, dim = -1).indices   
        maski = ~torch.zeros_like(x[..., 0]).scatter(1, indices, 1.).bool()
        kwargs.update(self_attn_context_mask = maski)
        
        print(kwargs)

        emb_type = self.word_emb_type(x[..., 0])
        emb_barbeat = self.word_emb_barbeat(x[..., 1])
        emb_tempo = self.word_emb_tempo(x[..., 2])
        emb_instrument = self.word_emb_instrument(x[..., 3])
        emb_note_name = self.word_emb_note_name(x[..., 4])
        emb_octave = self.word_emb_octave(x[..., 5])
        emb_duration = self.word_emb_duration(x[..., 6])
        
        embs2 = torch.cat(
            [
                x[..., 7].unsqueeze(-1).to(torch.float32),
                x[..., 8].unsqueeze(-1).to(torch.float32),
                x[..., 9].unsqueeze(-1).to(torch.float32),
                x[..., 10].unsqueeze(-1).to(torch.float32),
                x[..., 11].unsqueeze(-1).to(torch.float32),
                
            ], dim = -1)
        
                
        embs1 = torch.cat(
            [
                emb_type,
                emb_barbeat,
                emb_tempo,
                emb_instrument,
                emb_note_name,
                emb_octave,
                emb_duration,
            ], dim = -1)
        
        emb_linear = self.in_linear1(embs1)

        x = emb_linear + self.pos_emb(emb_linear)
        
        x = self.emb_dropout(x)
        x = self.project_emb(x)

        if not self.training:
            x.squeeze(0)
            
        b, n, f = x.shape
        if n <= 16 or n % 16 != 0:
            padding_size = 16 - (n % 16) if n % 16 != 0 else 0
            padding = (0, 0, 0, padding_size)
            tensor = torch.nn.functional.pad(x, padding, "constant", 0)
        b, n, f = tensor.shape
        tensor = tensor.reshape(b * n // 16, 16, f)
        tensor = tensor + self.pos_emb1(tensor)
        tensor= torch.cat((
            repeat(self.start_token, 'f -> b 1 f', b = b),
            tensor
        ), dim = -2)    
        
        print(kwargs)
        
        tensor, intermediates1 = self.attn_layers1(tensor, mask=mask, return_hiddens=True, **kwargs)
        tensor = tensor[:,0,:]
        tensor = tensor.reshape(b, n, f)
        tensor1 = torch.zeros(x.size(0), x.size(1), 512).to(tensor.device)
        
        for n in range(tensor.size(1)):
            if 16*(n+1) <= x.size(1):
                tensor1[:, 16*n:16*(n+1), :] = tensor[:, n, :]
            else:
                tensor1[:, 16*n:x.size(1), :] = tensor[:, n, :]
                
        tensor1 = torch.cat(
            [
                tensor1,
                embs1
            ], dim = -1)
        
        tensor1 = self.in_linear8(tensor1)
     
        x, intermediates = self.attn_layers(x, tensor1, mask=mask, return_hiddens=True, **kwargs)
        
        x = self.norm(x)     
  
        return x
