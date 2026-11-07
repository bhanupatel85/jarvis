# Development references

Source catalog: https://github.com/codecrafters-io/build-your-own-x
These are learning references, not installed capabilities. Linked tutorial contents have not been imported. Read relevant upstream documentation and check licenses before adapting code.

## Document retrieval and project knowledge
https://github.com/langchain-ai/rag-from-scratch
Use retrieval to locate relevant project documentation, keep source paths and line numbers, and distinguish retrieved text from instructions. Jarvis currently uses local keyword retrieval; embeddings and model training are not enabled.

## Durable databases and memory
https://cstack.github.io/db_tutorial/
Explore storage, indexes and transactions. Jarvis already uses atomic JSON storage; database migration should preserve user data and include recovery tests.

## Language models
https://github.com/rasbt/LLMs-from-scratch
Reference for understanding language model internals. Reading this guide does not train Jarvis or change model weights.
