# System Requirements Specification (SRS)

## Project: [LikaVal Official Website](https://www.likaval.com?utm_source=chatgpt.com)

---

# 1. Project Overview

The project consists of a lightweight automated content publishing platform for the LikaVal ceramics brand.

The solution will include:

* A static multilingual frontend website hosted on GitHub Pages
* A lightweight backend automation service running on Linux
* AI-assisted content generation using a local Ollama instance
* Automated publishing workflows for website and social commerce platforms

Primary goals:

* Showcase handmade ceramic products
* Publish new products automatically from uploaded media
* Support multilingual audiences
* Operate with minimal infrastructure requirements
* Avoid database dependencies by using editable text-based configuration and metadata files

---

# 2. High-Level Architecture

The system shall include the following components:

| Component                      | Description                                                  |
| ------------------------------ | ------------------------------------------------------------ |
| Frontend Website               | Static HTML-based multilingual website                       |
| Backend Automation Service     | Linux service responsible for synchronization and publishing |
| AI Processing Module           | Local Ollama-based content generation service                |
| GitHub Integration             | Static content deployment through Git push                   |
| External Publishing Connectors | Etsy, Facebook, and future platform integrations             |
| Configuration Layer            | Editable text-based configuration files                      |

---

# 3. Frontend Requirements

## 3.1 General Frontend Architecture

The frontend shall:

* Be implemented as a static HTML-based website
* Be hosted using GitHub Pages
* Be automatically updated by backend Git push operations
* Support responsive desktop and mobile layouts
* Operate without requiring server-side rendering

Recommended technologies:

* HTML5
* CSS3
* Vanilla JavaScript or lightweight frameworks
* Static asset optimization

---

## 3.2 Multilingual Support

The website shall support the following languages:

* English
* Russian
* Hebrew

The system architecture shall allow future language expansion.

Content shall be organized in a language-aware structure.

Example:

```text
/en/
/ru/
/he/
```

---

## 3.3 Russian Content Requirements

The Russian-language section shall include:

* Local ceramic workshops
* Pottery classes
* Community events
* Regional service information for Petah Tikva

Example content categories:

* “Мастер-классы по керамике”
* “Кружки лепки керамики”
* Local event announcements
* Workshop registration pages

SEO optimization shall target Russian-speaking audiences in Israel.

---

## 3.4 English Content Requirements

The English-language section shall include:

* Brand presentation
* Product catalog
* Available products for sale
* Sold product archive
* Custom order request capabilities

Each product page shall support:

* Images
* Short videos
* AI-generated descriptions
* Pricing in USD
* Availability status
* Handmade/custom-order indicators

Sold products shall remain visible for portfolio and marketing purposes.

---

# 4. Backend Requirements

## 4.1 General Backend Architecture

The backend shall:

* Run as a lightweight Linux service
* Be container-compatible
* Support execution on low-resource hardware
* Preferably support deployment on:

  * Raspberry Pi 4B
  * 4 GB RAM configuration

Recommended runtime:

* Python-based services
* Docker container deployment
* Cron or scheduler-based execution

---

## 4.2 Media Fetcher Module

The backend shall include a media fetcher service.

The fetcher shall:

* Execute once per day (configurable)
* Monitor a predefined Google Drive directory
* Detect newly added product folders
* Download:

  * Images
  * Short videos

Supported formats should include:

* JPG
* PNG
* WEBP
* MP4
* MOV

---

## 4.3 Folder Naming Convention

Product folders shall follow the structure:

```text
YYYYMMDD_PRICE
YYYYMMDD_PRICE_sold
```

Examples:

```text
20260517_200
20250101_100_sold
```

Definitions:

| Segment  | Meaning                                          |
| -------- | ------------------------------------------------ |
| YYYYMMDD | Product creation or publication date             |
| PRICE    | Product price in ILS                             |
| sold     | Optional status indicating unavailable inventory |

---

## 4.4 Pricing Conversion Logic

The backend shall convert prices from ILS to USD.

Requirements:

* Conversion coefficient shall be configurable
* Default conversion example:

```text
100 ILS → 80 USD
```

The conversion shall not require real-time exchange rates unless enabled in future versions.

---

## 4.5 AI Content Generation

The backend shall integrate with a local Ollama AI service.

The AI module shall:

* Analyze images and short videos
* Generate:

  * Product titles
  * Short descriptions
  * SEO tags
  * Social media captions
  * Etsy listing text
  * Facebook post drafts

The solution shall support configurable prompts.

The backend shall communicate with Ollama via configurable IP address and port settings.

Example deployment target:

* [Ollama](https://ollama.com?utm_source=chatgpt.com)

---

## 4.6 Publishing Automation

The backend shall automatically publish generated content to:

| Platform         | Action                            |
| ---------------- | --------------------------------- |
| GitHub           | Commit and push website updates   |
| Etsy             | Create or update listings         |
| Facebook         | Publish product posts             |
| Future Platforms | Extensible connector architecture |

Publishing operations shall support retry and failure logging.

---

## 4.7 State Management

The backend shall maintain publication state information.

Tracked data shall include:

* Processed folders
* Published products
* Sold products
* Publication timestamps
* Synchronization status
* Error logs

No relational database shall be required.

State information shall be stored using editable text files such as:

* JSON
* YAML
* TOML
* Markdown metadata files

All metadata files shall be Git-compatible.

---

# 5. Configuration Requirements

The system shall support editable configuration files.

Configuration shall include:

| Parameter                 | Description          |
| ------------------------- | -------------------- |
| Ollama IP address         | AI endpoint          |
| Google Drive directory ID | Media source         |
| Publishing schedules      | Cron timing          |
| Currency conversion ratio | ILS → USD            |
| Product lists             | Available/sold items |
| Platform credentials      | API integrations     |
| Frontend paths            | Output directories   |

Requirements:

* Human-readable format
* Git-compatible
* No database dependency
* Environment-specific overrides supported

Recommended formats:

```text
YAML
JSON
.env
```

---

# 6. Deployment Requirements

## 6.1 Supported Platforms

Primary deployment target:

* Linux
* ARM64 support
* Raspberry Pi 4B

Secondary targets:

* Ubuntu servers
* Docker hosts
* VPS systems

---

## 6.2 Containerization

The backend shall support Docker deployment.

Container requirements:

* Persistent mounted configuration volume
* Persistent logs volume
* Restart policy support
* Lightweight resource consumption

---

# 7. Non-Functional Requirements

## 7.1 Performance

The system shall:

* Operate within 4 GB RAM environments
* Support low CPU utilization
* Minimize storage consumption
* Optimize media processing workflows

---

## 7.2 Reliability

The system shall:

* Recover from interrupted synchronization tasks
* Avoid duplicate publishing
* Maintain processing logs
* Support resumable operations

---

## 7.3 Maintainability

The solution shall:

* Use modular architecture
* Support future platform connectors
* Allow easy configuration editing
* Avoid vendor lock-in

---

# 8. Future Expansion Possibilities

Potential future capabilities:

* Shopify integration
* Instagram publishing
* Telegram bot notifications
* AI-generated multilingual translations
* Automatic watermarking
* Inventory management
* Customer order forms
* Analytics dashboard
* Multi-brand support
* Video reel generation for social media

   
