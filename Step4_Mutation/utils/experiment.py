import torch
import numpy as np

class Mutation():
    def __init__(self, n_factors:int, n_vertices_num:np.array, n_vertices_type:np.array, subgraph_type:np.array, init_vertex:np.array): 
        assert n_factors == len(n_vertices_num)

        self.n_factors = n_factors
        self.n_vertices_num = n_vertices_num
        self.n_vertices_type = n_vertices_type
        self.suggested_init = torch.Tensor(init_vertex).long().unsqueeze(0)
        self.adjacency_mat = []
        self.fourier_freq = []
        self.fourier_basis = []

        for i in range(len(self.n_vertices_num)):
            vertice = self.n_vertices_num[i]
            if subgraph_type[i] == 'path':
                adjmat = torch.diag(torch.ones(vertice - 1), -1) + torch.diag(torch.ones(vertice - 1), 1)
                adjmat *= (vertice - 1.0)
            else:
                adjmat = torch.ones(vertice, vertice) - torch.eye(vertice)
                adjmat *= (vertice - 1.0)
            self.adjacency_mat.append(adjmat)

            degmat = torch.sum(adjmat, dim=0)
            laplacian = (torch.diag(degmat) - adjmat)

            eigval, eigvec = torch.linalg.eigh(laplacian)
            self.fourier_freq.append(eigval)
            self.fourier_basis.append(eigvec)