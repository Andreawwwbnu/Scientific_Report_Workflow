---
来源编号: AIDB15
标题: Build generative AI applications with Amazon Aurora and Amazon Bedrock Knowledge
  Bases
来源链接: https://aws.amazon.com/blogs/database/build-generative-ai-applications-with-amazon-aurora-and-amazon-bedrock-knowledge-bases/
发布主体: AWS官方博客
发布时间: '2024'
文献类型: 企业级生成式AI应用实践指南
可信度等级: 高（AWS官方方案，详解向量数据库支撑RAG系统的工程落地路径）
来源分类: 04-应用前景与多维价值评估
核心对应章节: '4.1'
标签:
- AWS
- RAG应用
- 生成式AI
- 向量数据库
- 工程落地
专题: 面向AI的新型数据库技术（AI-Native Database）
抓取时间: '2026-08-31 15:24:12'
---

# AIDB15 Build generative AI applications with Amazon Aurora and Amazon Bedrock Knowledge Bases

> **抓取状态：** 成功

[AWS Database Blog](/blogs/database/)

# Build generative AI applications with Amazon Aurora and Amazon Bedrock Knowledge Bases

[Amazon Bedrock](/bedrock/) is the easiest way to build and scale generative AI applications with foundational models (FMs). FMs are trained on vast quantities of data, allowing them to be used to answer questions on a variety of subjects. However, if you want to use an FM to answer questions about your private data that you have stored in your [Amazon Simple Storage Service](/s3) (Amazon S3) bucket or [Amazon Aurora PostgreSQL-Compatible Edition](/rds/aurora/postgresql-features/) database, you need to use a technique known as [Retrieval Augmented Generation](https://docs.aws.amazon.com/sagemaker/latest/dg/jumpstart-foundation-models-customize-rag.html) (RAG) to provide relevant answers for your customers.

[Amazon Bedrock Knowledge Bases](/bedrock/knowledge-bases/) is a fully managed RAG capability that allows you to customize FM responses with contextual and relevant company data. Amazon Bedrock Knowledge Bases automates the end-to-end RAG workflow, including ingestion, retrieval, prompt augmentation, and citations, eliminating the need for you to write custom code to integrate data sources and manage queries.

Integrating Amazon Bedrock with Amazon Aurora PostgreSQL lets you utilize features that help accelerate performance of vector similarity search for RAG. Aurora delivers queries 20 times faster with [pgvector](http://github.com/pgvector/pgvector/)’s HNSW indexing over other indexing methods. Additionally, [Amazon Aurora Optimized Reads](/blogs/database/new-amazon-aurora-optimized-reads-for-aurora-postgresql-with-up-to-8x-query-latency-improvement-for-i-o-intensive-applications/) can increase performance for vector search with [pgvector](http://github.com/pgvector/pgvector/) by up to nine times for workloads that exceed regular instance memory. This is on top of the performance and availability features that let you operate Aurora cost-effectively at global scale, including Aurora Serverless and [Amazon Aurora Global Database](/rds/aurora/global-database/).

In this post, we explore how to use [Amazon Aurora](/rds/aurora/) to build generative AI applications using RAG. We walk through setting up an Aurora cluster to be a knowledge base for Amazon Bedrock. We also demonstrate how to use the [Amazon Aurora Machine Learning](/rds/aurora/machine-learning/) extension to generate embeddings using Amazon Bedrock from simple SQL commands.

## Solution overview

The following diagram illustrates an example of a RAG workflow.

The RAG workflow contains two parts. The first part is taking unstructured data, such as text, images, and video, converting it into embeddings (vectors) using an embeddings model, and storing it in a vector database (Steps 1–3). An embedding is a numerical representation that you can use in a similarity search to find content that is most related to a query. The second part of the workflow is the request itself. The request is turned into an embedding and used to query the vector database to find content to augment the prompt (Steps 4–5). The output of the query is sent to the FM, which then sends the response to the user (Steps 6–7). Building a generative AI application that uses RAG requires orchestrating this workflow, which can require additional work beyond building the application logic.

Recently, AWS announced the general availability of [Amazon Bedrock Knowledge Bases](/bedrock/knowledge-bases/). With Amazon Bedrock Knowledge Bases you can give FMs and agents contextual information from your company’s private data sources for RAG to deliver more relevant, accurate, and customized responses. You can then use your knowledge base with [Amazon Bedrock Agents](/bedrock/agents/) to orchestrate multi-step tasks and facilitate prompt engineering. For more information, refer to [Knowledge Bases now delivers fully managed RAG experience in Amazon Bedrock](/blogs/aws/knowledge-bases-now-delivers-fully-managed-rag-experience-in-amazon-bedrock/).

In the following sections, we demonstrate how to set up Aurora as a knowledge base for Amazon Bedrock. We’ll also see how to use Aurora Machine Learning (ML) to generate embeddings using SQL commands.

## Prerequisites

This post assumes familiarity with navigating the [AWS Management Console](/console). For this example, you’ll also need the following resources and services enabled in your AWS account:

- An Aurora PostgreSQL cluster with
[Aurora ML](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/postgresql-ml.html)enabled - The
[RDS Data API](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Concepts.Aurora_Fea_Regions_DB-eng.Feature.Data_API.html)enabled for the Aurora cluster - Amazon S3
[AWS Secrets Manager](/secrets-manager/)[AWS Identity and Access Management](/iam/)(IAM)- Amazon Bedrock. You may need to request access to use specific foundational models in Amazon Bedrock. In this blog post, we used
**Anthropic Claude 2.1**and**Amazon Titan Embeddings G1 – Text**.

## Set up Aurora as a knowledge base for Amazon Bedrock

The first step to creating a knowledge base for Amazon Bedrock is to have content that can be used to augment a foundation model. In this example, we use a PDF version of the [PostgreSQL 16 manual](https://www.postgresql.org/files/documentation/pdf/16/postgresql-16-US.pdf). At the time of writing, PostgreSQL 16 was a new release and was not available for FM training on public data. Datasets used in RAG often have much more data, but we chose to keep this example simple.

### Configure an S3 bucket

To begin setting up a knowledge base for Amazon Bedrock, you’ll need to [create an S3 bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/create-bucket-overview.html). Make sure this bucket is private. This example uses a bucket called `bedrock-kb-demo-aurora`

. After you create the bucket, upload the PostgreSQL 16 manual to the bucket. The following screenshot shows what the upload looks like when it’s complete.

### Configure an Aurora PostgreSQL cluster

Next, create an Aurora PostgreSQL cluster. For full instructions, refer to [Using Aurora PostgreSQL as a Knowledge Base for Amazon Bedrock](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html). We highlight a few specific configuration options used in this example:

- On the Aurora console, create a new cluster.
- For
**Engine options**¸ select**Aurora (PostgreSQL Compatible)**. - For
**Engine version**, choose your engine version.

We selected PostgreSQL 15.5 for this example; we recommend using PostgreSQL 15.5 or higher so you can use the latest version of the open source pgvector extension.

- For
**Configuration options**, select either**Aurora Standard**or**Aurora I/O Optimized**.

We selected [Aurora I/O-Optimized](/blogs/database/new-amazon-aurora-optimized-reads-for-aurora-postgresql-with-up-to-8x-query-latency-improvement-for-i-o-intensive-applications/), which provides improved performance with predictable pricing for I/O-intensive applications.

- For
**DB instance class**, select your instance class.

We opted to use [Amazon Aurora Serverless v2](/rds/aurora/serverless/), which automatically scales your compute based on your application workload, so you only pay based on the capacity used.

- Enable the RDS Data API, which is used by Amazon Bedrock to access your Aurora cluster.
- Create your Aurora cluster.
- While your Aurora cluster is provisioning, navigate to the cluster on the Aurora console and choose the
**Configuration**tab. - Note the Amazon Resource Name (ARN) for the cluster, and save it for later.

You’ll need the ARN for configuring the knowledge base for Amazon Bedrock.

It takes about 10 minutes for the Aurora PostgreSQL cluster to finish provisioning. After the cluster is provisioned, you need to run a series of SQL commands to prepare your cluster to be a knowledge base.

- Log in to your Aurora cluster either as the admin user (for example,
`postgres`

) or a user that has the`rds_superuser`

privilege, and run the following code. Note the password that you create for`bedrock_user`

, because you’ll need it in a later step when configuring a secret in Secrets Manager. Also note the table names and column names, because they’ll be used in the knowledge base workflow on the Amazon Bedrock console.

The Aurora cluster is now set up to be used as a knowledge base for Amazon Bedrock. We’ll now create a secret in Secrets Manager that Amazon Bedrock will use to connect to the cluster.

## Create a secret in Secrets Manager

Secrets Manager lets you store your Aurora credentials so that they can be securely transmitted to applications. Complete the following steps to create your secret:

- On the Secrets Manager console, create a new secret.
- For
**Secret type**, select**Credentials for Amazon RDS database**. - Under
**Credentials**, enter a name for your user (for this post, we use`bedrock_user`

) and the password for that role. - In the
**Database**section, select the cluster you’re using for the knowledge base. - Choose
**Next**. - For
**Secret name**, enter a name for your secret. - Choose
**Next**. - Finish creating the secret and copy the secret ARN.

You’ll need the secret ARN for creating your knowledge base.

We’re now ready to use this Aurora cluster as a knowledge base for Amazon Bedrock.

## Create a knowledge base for Amazon Bedrock

We can now use our cluster as a knowledge base. Complete the following steps:

- On the Amazon Bedrock console, choose
**Knowledge base**under**Orchestration**in the navigation pane. - Choose
**Create knowledge base**. - For
**Knowledge base name**¸ enter a name. - For
**Runtime role**, select**Create and use a new service role**and enter a service role name. - Choose
**Next**. - For
**Choose an archive in S3**, select the S3 bucket to use as a data source and choose**Choose**.

For this post, we use the S3 bucket containing the PostgreSQL 16 manual that we uploaded earlier.

- For
**Embeddings**model, select your model (for this post, we use**Amazon Titan Embeddings G1 – Text**). - For
**Vector database**, select**Choose a vector store you have created**and select**Amazon Aurora**. - Provide the following additional information (note the examples we use for this post):
- For
**Amazon Aurora DB Cluster ARN**, enter the ARN you saved when creating your Aurora cluster. - For
**Database name**, enter`postgres`

. - For
**Table name**, enter`bedrock_integration.bedrock_kb`

. - For
**Secret ARN**, enter the ARN you saved when creating the secret for`bedrock_user`

. - For
**Vector field**, enter`embedding`

. - For
**Text field**, enter`chunks`

. - For
**Bedrock-managed metadata field**, enter`metadata`

. - For
**Primary key**, enter`id`

.

- For
- Choose
**Next**. - Review the summary page and choose
**Sync**.

This begins the process of converting the unstructured data stored in the S3 bucket into embeddings and storing them in your Aurora cluster.

The syncing operation may take minutes to hours to complete, based on the size of the dataset stored in your S3 bucket. During the sync operation, Amazon Bedrock downloads documents in your S3 bucket, divides them into chunks (we opt for the “default” strategy in this post), generates the vector embedding, and stores the embedding in your Aurora cluster. When the initial sync is complete, you’ll see that the data source shows as **Ready**.

Now you can use your knowledge base as in an agent for Amazon Bedrock. We can use this knowledge base as part of a test. For this example, we chose the PostgreSQL 16 manual as our dataset. This lets us see how RAG works in action, because foundational models may not yet have information on all the features of PostgreSQL 16.

In the following example, we use the **Test knowledge base** feature of Amazon Bedrock, choose the Anthropic Claude 2.1 model, and ask it a question about a PostgreSQL 16 feature—specifically, the `pg_stat_io`

view. The following screenshot shows our answer.

Using the provided question, Amazon Bedrock queried our Aurora cluster to get the additional context needed to answer the question. Our knowledge base contained information on how the new `pg_stat_io`

feature works, and was able to provide an augmented answer via Anthropic Claude. The test tool also cites the chunks it uses to provide attribution to how it delivered its response.

Now that we’ve seen how we can augment foundational model responses with Amazon Bedrock Knowledge Bases and an Aurora PostgreSQL cluster, let’s learn how we can generate embeddings directly from an Aurora cluster. This will be necessary to convert user questions into embeddings that can be compared to embeddings in Aurora with similarity search.

## Create an IAM role and policy for the Aurora cluster

Before you can start generating vector embeddings from Amazon Bedrock directly from Aurora, you may need to adjust the network configuration so your Aurora cluster can communicate with Amazon Bedrock. For more information on how to do this, see [Enabling network communication from Amazon Aurora MySQL to other AWS services](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraMySQL.Integrating.Authorizing.Network.html). These directions also apply to Aurora PostgreSQL clusters.

To allow Aurora ML to work with Amazon Bedrock, you must first create an IAM policy that allows the Aurora cluster to communicate with Amazon Bedrock models. Complete the following steps:

- On the IAM console, choose
**Policies**in the navigation pane, then choose**Create policy**. - In the policy editor, expand
**Bedrock**and under**Read**, select**InvokeModel**to allow that action. - Expand
**Resources**and select**Specific**. - For
**foundation-model**, select**Any**. As a best practice, make sure to only give access to the foundational models in Amazon Bedrock that your team requires. - For
**provisioned-model**, select**Any in this account**. As a best practice, make sure to only give access to provisioned models in Amazon Bedrock that your team requires. - Choose
**Next**. - For
**Policy name**, enter a name for your policy, such as`AuroraMLBedrock`

. - Choose
**Create policy**. - On the IAM console, choose
**Roles**in the navigation pane, then choose**Create role**. - For
**Trusted entity type**, select**AWS service**. - For
**Service or use case**, choose**RDS**. - Select
**RDS – Add Role to Database**. - Choose
**Next**.

Now we assign the IAM policy we created in the previous step to this IAM role.

- For
**Permission policies**, find and select the`AuroraMLBedrock`

policy. - Choose
**Next**. - In the
**Role details**section, enter a name (for this post,`AuroraMLBedrock`

) and a description. - Review the IAM role and confirm that the
`AuroraMLBedrock`

policy is attached. - Choose
**Create**to create the role.

Now we need to assign the `AuroraMLBedrock`

IAM role to the Aurora cluster.

- On the Amazon RDS console, navigate to your Aurora cluster details page.
- On the
**Connectivity & security**tab, locate the**Manage IAM roles**section. - For
**Add IAM roles to this cluster**, choose the`AuroraMLBedrock`

role. - For
**Feature**, choose**Bedrock**. - Choose
**Add role**.

Your cluster can now invoke models in Amazon Bedrock.

## Use Aurora ML to generate vector embeddings

Aurora machine learning is an Aurora feature that lets builders work directly with AWS ML services using SQL commands, including Amazon Bedrock, [Amazon SageMaker](/sagemaker/), and [Amazon Comprehend](/comprehend/). With [recent support for Amazon Bedrock](/about-aws/whats-new/2023/12/amazon-aurora-postgresql-integration-bedrock-generative-ai/), Aurora ML gives you access to foundational models and embedding generators, helping reduce latency when working with data already stored in you Aurora cluster. This includes two new functions: `aws_bedrock.invoke_model`

, which lets you use a foundational model from a SQL query, and `aws_bedrock.invoke_model_get_embeddings`

, which lets you generate an embedding from a SQL query. For more information, see [Using Amazon Aurora machine learning with Aurora PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/postgresql-ml.html).

Let’s see how we can use Aurora ML to generate an embedding from Amazon Bedrock. First, log in as an account with the `rds_superuser`

privilege (for example, `postgres`

) to your Aurora cluster and install the Aurora ML extension in your database:

You should see the following output:

You can now create embeddings directly from Aurora. The following example shows how to generate an embedding using the **Titan Embeddings G1 – Text** embedding model for the phrase “PostgreSQL I/O monitoring views”:

You should see the following output (abbreviated for clarity):

You can use the `aws_bedrock.invoke_model_get_embeddings`

function to generate embeddings from data that already exists in your database. However, because calling an embedding model on a single input can take 100–400 milliseconds to complete, you should use PostgreSQL’s stored procedure system on a batch query to prevent a single long-running transaction from blocking other processes.

The following example shows how we can add embeddings to an existing table and manage the batch import using an anonymous block. First, make sure the pgvector extension is installed in the database and create a table that will contain example data:

Now you can generate embeddings for this dataset in bulk using the following code. The example code loops through all of the records in the `documents`

table that don’t have an embedding. For each record, the code calls the Amazon Titan embedding model to generate the embedding, and updates and commits the result to the database.

In this section, we saw how to use Aurora ML to generate embeddings using Amazon Bedrock from data that already exists in your Aurora database. This technique helps speed up creating embeddings from the data in your database, because you can reduce latency by calling Amazon Bedrock directly without first transferring to a separate system.

## Clean up

If you don’t need to use any of the resources you created, delete them when you are finished:

- Empty and
[delete your S3 bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/delete-bucket.html). - If you no longer need to use the Aurora ML extension but would like to continue using your cluster, you can remove it from your Aurora cluster by running the following SQL command:
- Additionally, if you no longer need to use the Aurora ML extension but would like to continue using your Aurora cluster, you can remove the IAM role you created to access Amazon Bedrock from your cluster, and you may need to update some of your networking configurations.
- To delete your knowledge base, refer to
[Manage your knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-manage.html). - If you no longer need your Aurora cluster, follow the instructions in
[Deleting Aurora DB clusters and DB instances](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_DeleteCluster.html).

## Conclusion

RAG is a powerful technique that lets you combine domain-specific information with a FM to enrich responses in your generative AI applications. In this post, we covered multiple examples for how you can use Amazon Bedrock with Aurora to implement RAG for your generative AI applications. This included how to set up Amazon Aurora PostgreSQL as a knowledge base for Amazon Bedrock, and how to use Aurora ML to generate vector embeddings from Amazon Bedrock.

To learn more about using Amazon Aurora PostgreSQL and pgvector for AI and ML workloads, see [Leverage pgvector and Amazon Aurora PostgreSQL for Natural Language Processing, Chatbots and Sentiment Analysis](/blogs/database/leverage-pgvector-and-amazon-aurora-postgresql-for-natural-language-processing-chatbots-and-sentiment-analysis/).
