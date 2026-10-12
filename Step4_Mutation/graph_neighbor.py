import torch

def cartesian_neighbors(node, edge_matrix_list):
    all_neighbors = []
    for i in range(len(edge_matrix_list)):
        edge_matrix = edge_matrix_list[i]
        if node.dim() > 1:
            neighbors = edge_matrix[node[0, i]].nonzero(as_tuple = False).squeeze(1)
        else:
            neighbors = edge_matrix[node[i]].nonzero(as_tuple = False).squeeze(1)
        expanded_neighbors = node.repeat((neighbors.numel(), 1))
        expanded_neighbors[:, i] = neighbors
        all_neighbors.append(expanded_neighbors)
    if all_neighbors:
        return torch.cat(all_neighbors, dim = 0)
    else:
        return torch.empty(0)

def get_neighbors(nodes: torch.Tensor, edge_matrix: list, unique: bool = False) -> list:
    results = nodes[0].new_empty((0, nodes[0].numel()))
    all_neighbors = nodes[0].new_empty((0, nodes[0].numel()))
    curr_neighbors = nodes[0].new_empty((0, nodes[0].numel()))
    for node in nodes:
        if node.dim() > 1:
            node = node.squeeze(0)
        if node.dim() == 0:
            node = node.unsqueeze(0)
        node_neighbors = cartesian_neighbors(node.unsqueeze(0), edge_matrix)
        curr_neighbors = torch.cat([curr_neighbors, node_neighbors])
    added_indices = []
    if unique:
        for j in range(curr_neighbors.size(0)):
            if not torch.any(torch.all(all_neighbors == curr_neighbors[j], dim = 1)):
                added_indices.append(j)
        if len(added_indices) > 0:
            all_neighbors = torch.cat([all_neighbors, curr_neighbors[added_indices]])
    else:
        all_neighbors = torch.cat([all_neighbors, curr_neighbors])
    for i in all_neighbors:
        if not torch.any(torch.all(nodes == i, dim = 1)):
            results = torch.cat([results, i.unsqueeze(0)])
    return results