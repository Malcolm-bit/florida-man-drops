# florida-man-drops
"High-velocity apparel dropshipping automation engine. Built for rapid, data-driven scaling from viral trend identification to print-ready deployment."

Florida Man Drops Factory
An autonomous, AI-driven dropshipping pipeline that turns viral cultural moments into high-quality apparel designs and deploys them to Printful for fulfillment.
🛠 Features
Viral Trend Monitor: Automatically detects high-potential trends.
AI Design Engine: Utilizes DALL-E 3 to generate print-ready, high-resolution assets.
Resilient Factory: Robust Printful API integration with automated error handling and logging.
Self-Healing: Built-in retry logic using exponential backoff to ensure pipeline continuity.
🚀 Pipeline Flow
🏗 Repository Structure
generate.py: Trend identification and DALL-E image generation.
catalog.py: Metadata validation and local storage management.
upload.py: Printful API fulfillment and product publishing.
main.py: The master controller orchestrating the full automation loop.
