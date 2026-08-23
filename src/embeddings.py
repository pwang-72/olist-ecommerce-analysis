import torch
import torch.nn.functional as F



def mean_pooling(model_output, attention_mask):
    """
    Compute a sentence representation by averaging token embeddings,
    excluding padded tokens using the attention mask.
    """
        
    token_embeddings = model_output.last_hidden_state
    
    mask = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    
    return torch.sum(token_embeddings * mask, dim=1) / torch.clamp(
        mask.sum(dim=1),
        min=1e-9
    )


def encode_sentences(
    sentences,
    tokenizer,
    model,
    device,
    batch_size=32,
    max_length=128
):
    """
    Encode sentences into L2-normalized sentence embeddings.

    Sentences are tokenized in batches, mean-pooled over non-padding
    tokens, and normalized to unit length so that cosine similarity
    can be computed as a dot product.
    """

    all_embeddings = []

    model.eval()

    with torch.no_grad():

        for start in range(0, len(sentences), batch_size):

            batch_sentences = sentences[
                start:start + batch_size
            ]

            encoded = tokenizer(
                batch_sentences,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt"
            )

            encoded = {
                key: value.to(device)
                for key, value in encoded.items()
            }

            model_output = model(**encoded)

            embeddings = mean_pooling(
                model_output,
                encoded["attention_mask"]
            )

            # Normalize each sentence vector This makes every sentence vector have unit length. 
            # Therefore, cosine similarity can subsequently be calculated very efficiently with 
            # a matrix multiplication.
            embeddings = F.normalize(
                embeddings,
                p=2,
                dim=1
            )

            all_embeddings.append(
                embeddings.cpu()
            )

    return torch.cat(all_embeddings, dim=0)

def get_knn(embeddings, k):
    """
    Return the k nearest neighbors and their cosine similarities.for each embedding.

    Embeddings are assumed to be L2-normalized, so their dot product
    corresponds to cosine similarity. Each review's self-similarity
    is excluded.
    """

    similarity = embeddings @ embeddings.T

    similarity.fill_diagonal_(-float("inf"))

    neighbor_similarity, neighbor_indices = torch.topk(
        similarity,
        k=k,
        dim=1
    )

    return neighbor_indices, neighbor_similarity