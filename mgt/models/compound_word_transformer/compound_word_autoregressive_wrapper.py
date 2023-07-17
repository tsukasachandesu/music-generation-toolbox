import numpy as np
import torch
from torch import nn
import torch.nn.functional as F

from mgt.models.compound_word_transformer.compound_word_transformer_utils import COMPOUND_WORD_PADDING, pad
from mgt.models.compound_word_transformer.compound_word_transformer_wrapper import CompoundWordTransformerWrapper
from mgt.models.utils import get_device
from einops import rearrange, reduce, repeat

def log(t, eps = 1e-20):
    return t.clamp(min = eps).log()

def gumbel_noise(t):
    noise = torch.zeros_like(t).uniform_(0, 1)
    return -log(-log(noise))

def gumbel_sample(t, temperature = 1., dim = -1):
    return ((t / max(temperature, 1e-10)) + gumbel_noise(t)).argmax(dim = dim)

def top_k(logits, thres = 0.9):
    k = int((1 - thres) * logits.shape[-1])
    val, ind = torch.topk(logits, k)
    probs = torch.full_like(logits, -torch.finfo(logits.dtype).max)
    probs.scatter_(1, ind, val)
    return probs



def type_mask(target):
    return target[..., 0] != 0

def calculate_loss1(predicted, target, loss_mask):
    trainable_values = torch.sum(loss_mask)
    if trainable_values == 0:
        return 0

    loss = F.mse_loss(predicted[:, ...], target, reduction = 'none')
    loss = loss * loss_mask.unsqueeze(-1)
    loss = torch.sum(loss) / trainable_values

    return loss

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

def calculate_loss(predicted, target, loss_mask):
    trainable_values = torch.sum(loss_mask)
    if trainable_values == 0:
        return 0

    loss = F.cross_entropy(predicted[:, ...].permute(0, 2, 1), target, reduction='none')
    loss = loss * loss_mask
    loss = torch.sum(loss) / trainable_values
    return loss

class CompoundWordAutoregressiveWrapper(nn.Module):
    def __init__(self, net: CompoundWordTransformerWrapper, ignore_index=-100, pad_value=None):
        super().__init__()
        if pad_value is None:
            pad_value = COMPOUND_WORD_PADDING
        self.pad_value = pad_value
        self.ignore_index = ignore_index
        self.net = net
        self.max_seq_len = net.max_seq_len
        self.soft = nn.Softmax()

    @torch.no_grad()
    def generate(self, prompt, output_length=100, selection_temperatures=None, selection_probability_tresholds=None):
        self.net.eval()

        print('------ initiate ------')
        final_res = prompt.copy()
        last_token = final_res[-self.max_seq_len:]
        input_ = torch.tensor(np.array([last_token])).long().to(get_device())
        h, y_type = self.net.forward_hidden(input_)
        
        print('------ generate ------')
        for _ in range(output_length):
            # sample others
            next_arr = self.net.forward_output_sampling(
                h[:, -1:, :],
                y_type[:, -1:, :],                
                selection_temperatures=selection_temperatures,
                selection_probability_tresholds=selection_probability_tresholds)

            final_res.append(next_arr.tolist())

            # forward
            last_token = final_res[-self.max_seq_len:]
            input_ = torch.tensor(np.array([last_token])).long().to(get_device())
            h, y_type = self.net.forward_hidden(input_)

        return final_res

    def train_step(self, x, **kwargs):
                
        xi = x[:, :-1, :]
        target = x[:, 1:, :]

        z = target[:, :, 1:7] - 1
        i_special_minus1 = 12
        j_special_minus1 = 9 
        k_special_minus1 = 64 
        r_special_minus1 = 108
        
        mask_minus1 = z == -1
        i_tensor = torch.where(mask_minus1, i_special_minus1, z // (64 * 9))
        j_tensor = torch.where(mask_minus1, j_special_minus1,  (z // 64) % 9)
        k_tensor = torch.where(mask_minus1, k_special_minus1,  z % 64)
        r_tensor = torch.where(mask_minus1, r_special_minus1,  z // 64)
        
        h, proj_type = self.net.forward_hidden(xi,**kwargs)
        proj_barbeat, proj_tempo, proj_instrument, proj_note_name, proj_octave, proj_duration,a1,a2,a3,b1,b2,b3,c1,c2,c3,d1,d2,d3,e1,e2,e3,f1,f2,f3 = self.net.forward_output(h, target)
        
        type_loss = calculate_loss(proj_type, target[..., 0], type_mask(target))
        barbeat_loss = calculate_loss(proj_barbeat, target[..., 1], type_mask(target))
        tempo_loss = calculate_loss(proj_tempo, target[..., 2], type_mask(target))
        instrument_loss = calculate_loss(proj_instrument, target[..., 3], type_mask(target))
        note_name_loss = calculate_loss(proj_note_name, target[..., 4], type_mask(target))
        octave_loss = calculate_loss(proj_octave, target[..., 5], type_mask(target))
        duration_loss = calculate_loss(proj_duration, target[..., 6], type_mask(target))
        

        
        proj = torch.cat([proj_barbeat.unsqueeze(3), proj_tempo.unsqueeze(3), proj_instrument.unsqueeze(3), proj_note_name.unsqueeze(3), proj_octave.unsqueeze(3), proj_duration.unsqueeze(3)],-1)
        print(proj.shape)
        proj = proj[:,:,1:,:]
        print(proj.shape)
        x1,x2,x3,x4 = proj.shape
        proj = proj.reshape(-1,x2,x3,1)
        print(proj.shape)
        x1,x2,x3 ,x4= proj.shape
        proj = proj.reshape(x1,x2,64,-1)
        print(proj.shape)
        proj1 = torch.sum(proj,-1)
        print(proj1.shape)
        proj = torch.cat([proj[:,:,0].unsqueeze(2), proj1],-1)
        print(proj.shape)
        print( type_mask(target.repeat((6,1))))
        proj = calculate_loss(proj, k_tensor.reshape(-1,x2,1).squeeze(2), type_mask(target.repeat((6,1,1))))
        
        return type_loss, barbeat_loss, tempo_loss, instrument_loss, note_name_loss, octave_loss, duration_loss
   
   

