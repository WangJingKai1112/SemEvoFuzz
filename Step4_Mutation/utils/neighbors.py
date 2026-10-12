import torch

def get_neighbors_1(x, edge_mat, uniquely=False):
    result = x[0].new_empty((0, x[0].numel()))
    nbds = x[0].new_empty((0, x[0].numel()))
    nbd = x[0].new_empty((0, x[0].numel()))
    
    for i in x:
        if i.dim() > 1:
            i = i.squeeze(0)
        
        if i.dim() == 0:
            i = i.unsqueeze(0)
        
        nbd_i = _cartesian_neighbors(i.unsqueeze(0), edge_mat)
        nbd = torch.cat([nbd, nbd_i])
    
    added_ind = []
    if uniquely:
        for j in range(nbd.size(0)):
            if not torch.any(torch.all(nbds == nbd[j], dim=1)):
                added_ind.append(j)
        if len(added_ind) > 0:
            nbds = torch.cat([nbds, nbd[added_ind]])
    else:
        nbds = torch.cat([nbds, nbd])
    
    for i in nbds:
        if not torch.any(torch.all(x == i, dim=1)):
            result = torch.cat([result, i.unsqueeze(0)])
    
    return result

def _cartesian_neighbors(x, edge_mat_list):    
    neighbor_list = []
    for i in range(len(edge_mat_list)):
        edge_mat = edge_mat_list[i]
        
        if x.dim() > 1:
            nbd_i_elm = edge_mat[x[0, i]].nonzero(as_tuple=False).squeeze(1)
        else:
            nbd_i_elm = edge_mat[x[i]].nonzero(as_tuple=False).squeeze(1)

        nbd_i = x.repeat((nbd_i_elm.numel(), 1))
        nbd_i[:, i] = nbd_i_elm
        neighbor_list.append(nbd_i)
    
    if neighbor_list:
        return torch.cat(neighbor_list, dim=0)
    else:
        return torch.empty(0)
