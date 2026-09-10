# BACKEND ENGINEERING & SYSTEM ARCHITECTURECONTENT MASTER LIST

A social-media topic bank focused on the things developers often overlook—and discover too late.

Core positioning: Teach developers not only how to build software, but what is actually happening underneath their applications: memory, processes, operating systems, networking, databases, media pipelines, distributed systems, reliability, security, performance, and cloud architecture.

**328 topics across 18 sections.**

## Post formula

- HOOK — Start with a surprising statement or question.
- PROBLEM — Show the real engineering problem.
- REAL SCENARIO — Give a production-style example.
- WHY IT HAPPENS — Explain the underlying mechanism.
- ARCHITECTURE / SOLUTION — Show what a robust implementation does.
- TAKEAWAY — End with one practical lesson developers can remember.

## Sections

- **1. Database & Data Architecture** — 20 topics
- **2. API & Backend Design** — 18 topics
- **3. Distributed Systems & Architecture** — 18 topics
- **4. Queues, Events & Background Jobs** — 12 topics
- **5. Memory & Runtime Internals** — 21 topics
- **6. Processes, Threads & Concurrency** — 27 topics
- **7. Operating System & Low-Level Backend** — 29 topics
- **8. Media Processing — Images** — 13 topics
- **9. Media Processing — Video** — 25 topics
- **10. Media Processing — Audio** — 9 topics
- **11. Networking From the Backend Perspective** — 27 topics
- **12. Storage & Filesystems** — 20 topics
- **13. Performance Engineering** — 24 topics
- **14. Reliability & Production Engineering** — 17 topics
- **15. Security Developers Often Underestimate** — 17 topics
- **16. Architecture & Cloud Cost** — 11 topics
- **17. Signature 'What Actually Happens?' Series** — 10 topics
- **18. Strong Thought-Provoking Posts** — 10 topics

## 1. Database & Data Architecture

- `T001` Your database is not your application cache
- `T002` Why database indexes can make your system slower
- `T003` The hidden cost of SELECT *
- `T004` What happens when your database connection pool is exhausted?
- `T005` Database connection pooling: the bottleneck developers overlook
- `T006` Why your database works perfectly in development but collapses in production
- `T007` Read replicas don't automatically solve database scaling
- `T008` When should you use SQL vs NoSQL?
- `T009` The danger of storing everything in one giant table
- `T010` Soft deletes: the database problem nobody talks about
- `T011` Database migrations can take down production
- `T012` What happens when two requests update the same record simultaneously?
- `T013` Race conditions in databases
- `T014` Optimistic vs pessimistic locking
- `T015` Why distributed transactions are painful
- `T016` Data consistency vs availability: what are you actually choosing?
- `T017` The hidden consequences of deleting data
- `T018` Why your database backup strategy may be useless
- `T019` Point-in-time recovery: the feature you hope you never need
- `T020` How bad database queries become an infrastructure problem

## 2. API & Backend Design

- `T021` Idempotency: how to prevent duplicate payments/orders
- `T022` Why retrying an API request can make things worse
- `T023` Timeouts: the backend setting developers underestimate
- `T024` Your API needs a timeout—even if the service is reliable
- `T025` Rate limiting isn't just about stopping hackers
- `T026` Pagination: why OFFSET can become expensive
- `T027` Cursor pagination vs offset pagination
- `T028` API versioning: what happens when you change your response format?
- `T029` Backward compatibility in APIs
- `T030` Why APIs should not expose your database structure
- `T031` The danger of trusting data from your frontend
- `T032` Request validation vs business-rule validation
- `T033` Why an API returning HTTP 200 for everything is a problem
- `T034` How poorly designed error responses make systems harder to maintain
- `T035` The hidden complexity of file uploads
- `T036` Why large API responses can kill performance
- `T037` API aggregation and the N+1 request problem
- `T038` What happens when one API depends on five other APIs?

## 3. Distributed Systems & Architecture

- `T039` Distributed systems fail in ways local applications don't
- `T040` The fallacy that the network is reliable
- `T041` What happens when Service A is up but Service B is down?
- `T042` Cascading failures: how one small failure takes down everything
- `T043` Circuit breakers: stopping failures from spreading
- `T044` Bulkheads: isolating failures inside your architecture
- `T045` Retries + timeouts + queues: how they interact
- `T046` Why microservices can make a simple system complicated
- `T047` When NOT to use microservices
- `T048` The modular monolith developers overlook
- `T049` Service discovery: how does one service find another?
- `T050` What happens when two services disagree about the same data?
- `T051` Eventual consistency explained with real-world examples
- `T052` Distributed locks: why they're harder than they look
- `T053` The problem with assuming requests arrive in order
- `T054` Exactly-once delivery doesn't mean what you think
- `T055` At-least-once vs at-most-once message delivery
- `T056` Why distributed systems need correlation IDs

## 4. Queues, Events & Background Jobs

- `T057` Why your backend shouldn't do everything synchronously
- `T058` Message queues: when and why to use them
- `T059` RabbitMQ/Kafka/SQS: they're solving different problems
- `T060` Dead-letter queues: the safety net developers forget
- `T061` What happens to a job when your worker crashes halfway through?
- `T062` Designing jobs that are safe to retry
- `T063` Duplicate messages and idempotent consumers
- `T064` Queue backpressure: what happens when producers are faster than consumers?
- `T065` Poison messages: when one bad message keeps crashing your worker
- `T066` Why background jobs need monitoring
- `T067` Event-driven architecture isn't automatically scalable
- `T068` The hidden complexity of event ordering

## 5. Memory & Runtime Internals

- `T069` Stack vs heap: what actually happens when your code runs?
- `T070` What is a memory leak in a backend application?
- `T071` Garbage collection: what happens when GC pauses your application?
- `T072` Why increasing RAM doesn't always fix performance
- `T073` Memory fragmentation
- `T074` Virtual memory vs physical memory
- `T075` What is a memory page?
- `T076` Page faults and why they matter
- `T077` Swap: why your available RAM can be misleading
- `T078` Memory-mapped files
- `T079` Buffering vs streaming
- `T080` Why loading a 2 GB file into memory can kill your server
- `T081` How one large request can cause an OOM crash
- `T082` Out-of-memory killers: what happens when the OS runs out of memory?
- `T083` Heap growth over time: finding hidden memory leaks
- `T084` Object allocation and its performance cost
- `T085` Why copying large objects is expensive
- `T086` Zero-copy: moving data without unnecessarily copying it
- `T087` Reference vs value semantics and memory implications
- `T088` How connection pools consume memory
- `T089` Why caching everything can eventually hurt your application

## 6. Processes, Threads & Concurrency

- `T090` Process vs thread: what is actually different?
- `T091` What happens when you start a backend server?
- `T092` Threads vs async/await
- `T093` Concurrency vs parallelism
- `T094` CPU-bound vs I/O-bound workloads
- `T095` Context switching and its hidden cost
- `T096` Race conditions
- `T097` Deadlocks
- `T098` Starvation
- `T099` Thread pools
- `T100` Worker pools
- `T101` Process pools
- `T102` Why spawning a process for every request is dangerous
- `T103` How Node.js handles concurrency
- `T104` Python's GIL and what it actually means
- `T105` Why async doesn't automatically make code faster
- `T106` Event loops explained from the OS upward
- `T107` What happens when your event loop is blocked?
- `T108` One CPU-heavy operation can freeze an entire server
- `T109` Process isolation
- `T110` Child processes
- `T111` Signals: SIGTERM, SIGKILL, SIGINT
- `T112` Graceful shutdown and what the OS actually does
- `T113` Zombie processes
- `T114` Orphan processes
- `T115` Process supervisors
- `T116` Why containers are not lightweight virtual machines

## 7. Operating System & Low-Level Backend

- `T117` What actually happens when you run ./server?
- `T118` User space vs kernel space
- `T119` System calls
- `T120` File descriptors
- `T121` Why everything is a file in Unix-like systems
- `T122` Sockets as file descriptors
- `T123` How read() and write() actually work
- `T124` Blocking vs non-blocking I/O
- `T125` epoll, kqueue and scalable I/O
- `T126` Interrupts
- `T127` CPU scheduling
- `T128` CPU cache and why locality matters
- `T129` L1 vs L2 vs L3 cache
- `T130` Why sequential memory access can be dramatically faster
- `T131` NUMA
- `T132` Endianness
- `T133` Binary vs text data
- `T134` Serialization/deserialization costs
- `T135` fork() and process creation
- `T136` Signals and process lifecycle
- `T137` File locks
- `T138` OS-level resource limits
- `T139` ulimit
- `T140` Open-file limits
- `T141` Why your application can run out of file descriptors
- `T142` /proc: looking inside a running Linux system
- `T143` How Linux actually manages memory
- `T144` What happens when a process crashes?
- `T145` Core dumps and debugging native crashes

## 8. Media Processing — Images

- `T146` Why resizing an image can consume surprising amounts of RAM
- `T147` JPEG vs PNG vs WebP vs AVIF
- `T148` Image compression isn't just about file size
- `T149` Image dimensions vs file size
- `T150` Thumbnail generation at scale
- `T151` Image processing pipelines
- `T152` EXIF metadata
- `T153` Image orientation problems
- `T154` Progressive JPEGs
- `T155` Lossy vs lossless compression
- `T156` CPU vs GPU image processing
- `T157` Why image processing should often happen asynchronously
- `T158` How to prevent maliciously large image dimensions from taking down your server

## 9. Media Processing — Video

- `T159` What actually happens when you upload a video?
- `T160` Video codecs vs containers
- `T161` H.264 vs H.265 vs AV1
- `T162` MP4 vs MKV vs WebM
- `T163` Encoding vs transcoding
- `T164` Bitrate
- `T165` Resolution
- `T166` Frame rate
- `T167` Keyframes/I-frames
- `T168` GOP
- `T169` Why video transcoding is CPU-intensive
- `T170` Hardware vs software encoding
- `T171` GPU acceleration
- `T172` FFmpeg architecture
- `T173` Why you shouldn't process a 2-hour video inside an HTTP request
- `T174` Background video-processing workers
- `T175` Video transcoding queues
- `T176` Adaptive bitrate streaming
- `T177` HLS vs DASH
- `T178` Generating video thumbnails
- `T179` Generating previews
- `T180` Extracting audio from video
- `T181` Video metadata extraction
- `T182` Streaming video vs downloading the entire file
- `T183` How YouTube/Netflix-style video delivery works at a high level

## 10. Media Processing — Audio

- `T184` WAV vs MP3 vs AAC vs Opus
- `T185` Bitrate vs sample rate
- `T186` Audio transcoding
- `T187` Audio normalization
- `T188` Waveforms
- `T189` Speech-to-text pipelines
- `T190` Why audio processing can become CPU-heavy
- `T191` Streaming audio processing
- `T192` Chunking large audio files

## 11. Networking From the Backend Perspective

- `T193` What actually happens when you type a URL?
- `T194` DNS resolution
- `T195` TCP handshake
- `T196` TLS handshake
- `T197` HTTP/1.1 vs HTTP/2 vs HTTP/3
- `T198` TCP vs UDP
- `T199` Packets
- `T200` MTU
- `T201` Packet fragmentation
- `T202` TCP congestion control
- `T203` TCP retransmission
- `T204` Keep-alive connections
- `T205` Connection pooling
- `T206` Socket exhaustion
- `T207` Ephemeral ports
- `T208` NAT
- `T209` Load balancers
- `T210` Reverse proxies
- `T211` Why localhost is not the same as production networking
- `T212` Why network latency exists even when servers are close
- `T213` Bandwidth vs latency
- `T214` Head-of-line blocking
- `T215` WebSockets
- `T216` Server-Sent Events
- `T217` Long polling
- `T218` Streaming HTTP responses
- `T219` Network backpressure

## 12. Storage & Filesystems

- `T220` What actually happens when you save a file?
- `T221` RAM vs SSD vs HDD
- `T222` Why SSDs are faster
- `T223` Sequential vs random I/O
- `T224` Filesystems
- `T225` Inodes
- `T226` File descriptors
- `T227` File permissions
- `T228` Journaling
- `T229` Disk I/O bottlenecks
- `T230` Why deleting a file doesn't necessarily mean the data is immediately erased
- `T231` Temporary files
- `T232` Disk space vs inode exhaustion
- `T233` Why /tmp can become a production problem
- `T234` Object storage vs local filesystem
- `T235` S3-style object storage architecture
- `T236` Multipart uploads
- `T237` Resumable uploads
- `T238` Uploading a 10 GB file safely
- `T239` Why storing user uploads on your application server is often a bad idea

## 13. Performance Engineering

- `T240` Profiling vs guessing
- `T241` CPU profiling
- `T242` Memory profiling
- `T243` Flame graphs
- `T244` Latency distributions
- `T245` p50 vs p95 vs p99
- `T246` Benchmarking mistakes
- `T247` Load testing
- `T248` Stress testing
- `T249` Soak testing
- `T250` Concurrency testing
- `T251` Cache performance
- `T252` Database performance
- `T253` Network performance
- `T254` Disk performance
- `T255` CPU cache misses
- `T256` Memory bandwidth
- `T257` Lock contention
- `T258` Queue latency
- `T259` Backpressure
- `T260` Throughput vs latency
- `T261` Amdahl's Law
- `T262` Little's Law
- `T263` Why optimizing the wrong thing changes nothing

## 14. Reliability & Production Engineering

- `T264` What happens when your server restarts during a transaction?
- `T265` Graceful shutdown: the feature developers forget
- `T266` Health checks aren't as simple as /health
- `T267` Liveness vs readiness checks
- `T268` What happens when your deployment fails halfway through?
- `T269` Blue-green vs rolling deployments
- `T270` Zero-downtime deployments
- `T271` Feature flags as a reliability mechanism
- `T272` Why every production system needs observability
- `T273` Logs aren't observability
- `T274` Metrics vs logs vs traces
- `T275` Distributed tracing: finding where 5 seconds disappeared
- `T276` Alert fatigue
- `T277` Why monitoring CPU usage isn't enough
- `T278` Disaster recovery vs backups
- `T279` RTO vs RPO
- `T280` Designing for failure instead of assuming success

## 15. Security Developers Often Underestimate

- `T281` Authentication is not authorization
- `T282` Why checking permissions only on the frontend is useless
- `T283` Broken access control: the vulnerability hiding in ordinary APIs
- `T284` Why you shouldn't trust IDs coming from users
- `T285` IDOR: changing /users/123 to /users/124
- `T286` Secrets don't belong in your Git repository
- `T287` Environment variables aren't automatically secure
- `T288` JWTs: what developers misunderstand about them
- `T289` Why JWT logout is complicated
- `T290` Refresh tokens and token rotation
- `T291` Password hashing vs encryption
- `T292` Why passwords should never be encrypted
- `T293` SQL injection still exists—in different forms
- `T294` SSRF: when your server becomes the attacker's network tool
- `T295` Why internal APIs still need authentication
- `T296` The danger of overly powerful service accounts
- `T297` Logging sensitive information without realizing it

## 16. Architecture & Cloud Cost

- `T298` Your architecture can be technically correct and financially terrible
- `T299` The hidden cost of excessive microservices
- `T300` Why serverless can become expensive
- `T301` Data transfer/egress costs developers forget
- `T302` The cost of unnecessary API calls
- `T303` Over-provisioning infrastructure
- `T304` Under-provisioning infrastructure
- `T305` Cloud architecture is also financial architecture
- `T306` Why storing everything forever costs more than you think
- `T307` The hidden cost of logs
- `T308` Why just adding another managed service can become technical debt

## 17. Signature 'What Actually Happens?' Series

- `T309` What actually happens when you upload a 500 MB video?
- `T310` What actually happens when your backend receives 10,000 requests at once?
- `T311` What actually happens when your server runs out of RAM?
- `T312` What actually happens when you start a backend server?
- `T313` What actually happens between clicking Upload and seeing your processed video?
- `T314` What actually happens when a Linux process crashes?
- `T315` What actually happens when your database connection pool runs out?
- `T316` What actually happens when one dependency becomes slow?
- `T317` What actually happens when a request times out?
- `T318` What actually happens when two requests modify the same record simultaneously?

## 18. Strong Thought-Provoking Posts

- `T319` Your system didn't fail because you had too much traffic. It failed because one dependency had no timeout.
- `T320` A retry mechanism can turn a small outage into a major outage.
- `T321` The database is usually not the first thing that breaks. The things around it are.
- `T322` Your API may be fast—but is your system fast?
- `T323` Microservices don't remove complexity. They move complexity into the network.
- `T324` A backup you have never restored is a hope, not a recovery strategy.
- `T325` If your system cannot survive a server restarting, it isn't production-ready.
- `T326` Every distributed system eventually becomes a failure-management system.
- `T327` Your frontend can hide a broken backend. Production traffic won't.
- `T328` The most dangerous bugs are often not crashes—they are correct-looking wrong results.

Hook: Your server has 16 GB of RAM. Why can't your application use all 16 GB?

The goal of the series is to move from surface-level coding tutorials into systems thinking: help developers understand the runtime, OS, network, storage, database, infrastructure, and failure modes beneath the code they write.
