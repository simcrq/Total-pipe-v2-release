"""v24 warm start with measured-content, role and archetype conditioning."""
import torch
from torch import nn
from layoutdiffusion_demo.model import LayoutDenoiser, timestep_embedding
from layoutdiffusion_demo.config import DemoConfig
from .contracts import ARCHETYPES, ROLES, FEATURES, MAX_UNITS


class ContentDenoiser(LayoutDenoiser):
    def __init__(self,cfg):
        super().__init__(cfg)
        self.content = nn.Sequential(nn.Linear(FEATURES,cfg.d_model),nn.SiLU(),nn.Linear(cfg.d_model,cfg.d_model))
        self.role = nn.Embedding(len(ROLES),cfg.d_model)
        self.archetype = nn.Embedding(len(ARCHETYPES),cfg.d_model)

    def forward(self,labels,noisy_coords,t,valid_mask,features,roles,archetype):
        b,n=labels.shape
        h=self.label_emb(labels)+self.content(features)+self.role(roles)+self.archetype(archetype)[:,None,:]
        for j in range(4): h=h+self.coord_emb[j](noisy_coords[...,j])
        h=h+self.known_emb(torch.zeros_like(noisy_coords)).sum(2)
        h=h+self.pos_emb(torch.arange(n,device=labels.device))[None]
        h=h+self.time_mlp(timestep_embedding(t,self.cfg.d_model))[:,None,:]
        h=self.norm(self.transformer(h,src_key_padding_mask=~valid_mask))
        return torch.stack([head(h) for head in self.heads],2)


def warm_start(path):
    data=torch.load(path,map_location='cpu',weights_only=False)
    cfg=DemoConfig(**{**data['config'],'max_elements':MAX_UNITS})
    model=ContentDenoiser(cfg)
    if 'content.0.weight' in data['model']:
        model.load_state_dict(data['model'],strict=True)
        return model,cfg
    weights=data['model'].copy(); old=weights.pop('pos_emb.weight')
    missing,unexpected=model.load_state_dict(weights,strict=False)
    assert not unexpected and all(k.startswith(('pos_emb','content','role','archetype')) for k in missing)
    with torch.no_grad(): model.pos_emb.weight[:len(old)].copy_(old)
    return model,cfg


@torch.inference_mode()
def sample(model,batch,seed=0,temperature=.65):
    labels,mask,features,roles,arch=batch
    device=labels.device; cfg=model.cfg
    generator=torch.Generator(device=device).manual_seed(seed)
    x=torch.full((*labels.shape,4),cfg.num_bins,dtype=torch.long,device=device)
    for step in range(cfg.timesteps,0,-1):
        t=torch.full((len(labels),),step,dtype=torch.long,device=device)
        logits=model(labels,x,t,mask,features,roles,arch)/temperature
        x=torch.multinomial(logits.softmax(-1).reshape(-1,cfg.num_bins),1,generator=generator).reshape_as(x)
        if step>1:
            u=torch.rand(x.shape,device=device,generator=generator); frac=(step-1)/cfg.timesteps
            x[u<frac*.70]=cfg.num_bins
            rand=torch.randint(cfg.num_bins,x.shape,device=device,generator=generator)
            rr=(u>=frac*.70)&(u<frac*.84); x[rr]=rand[rr]
        x[~mask]=0
    return x
