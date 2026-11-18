# Knowledge base: what to download and how to set it up

> **Status:** planned for Parsemaxxing v2 (Phase 20, design section 7.12). This guide describes how the import will work once it is built. Until then, Parsemaxxing runs without the knowledge base.

Parsemaxxing's agents work better when they can look things up: the exact meaning of a `props.conf` setting, how Splunk breaks lines, where index-time settings must live in a cluster, which tags a CIM dataset needs. This guide tells you which Splunk manuals to download as PDFs, where to get them, and how to load them into Parsemaxxing, on a server with or without internet.

## 1. What Parsemaxxing already has without any download

You do not need any PDF for Parsemaxxing to work. These sources are loaded automatically:

| Source | Where it comes from | What it gives the agents |
| --- | --- | --- |
| Splunk `.spec`, `.example` and default config files | Your own Splunk install (the sandbox, an uploaded bundle, or the relay) | Every setting, its syntax and default, for your exact Splunk version |
| CIM data model definitions | The CIM add-on package you upload once per version (see section 1a) | Every model, dataset, field, description, expected value and required tag |
| Splunk agent skills | Shipped with Parsemaxxing (Apache 2.0) | Splunk's own guidance on field extraction, CIM mapping, ingestion and add-on lifecycle |
| Project notes | Shipped with Parsemaxxing | Short reviewed notes on how Splunk parsing works |
| Approved add-ons | Your own Parsemaxxing | Configs of add-ons your team already approved, as examples |
| Fix memory | Your own Parsemaxxing's past runs | Which change fixed a similar failure before (configs and error messages only, never log samples) |
| Installed vendor add-ons | Read from each connected environment | How existing add-ons parse similar products, as unverified examples (vendor add-ons can be wrong too), and a warning if one already owns the sourcetype |

**Optional: reference add-on library.** For offline environments, or to give the agents more examples, an admin can upload add-on packages downloaded from Splunkbase under the team's own account in **Knowledge → Reference add-ons**. Parsemaxxing only reads their configuration files, never runs anything in them, and keeps them inside this install. Good choices cover formats you meet often: an add-on for Windows event logs, one for a syslog firewall, one for Linux, and one for a web proxy.

### 1a. Upload the CIM add-on package (required for CIM mapping)

Parsemaxxing reads the CIM data models from the CIM add-on package itself, and installs the same package on its sandbox, so tests run against exactly the CIM your environments use.

1. On each environment's page, Parsemaxxing shows the CIM add-on version installed there (read from Splunk, or entered by you for an offline environment).
2. Download **that exact version** of "Splunk Common Information Model (CIM)" from Splunkbase (app 1621), under your own Splunkbase account. Use the version history on Splunkbase if the installed version is not the latest. The same version means the same x.y.z, for example 8.7.0, not just 8.7.
3. Go to **Environments → CIM library → Upload** and choose the downloaded file (`.tgz` or `.spl`). Parsemaxxing shows the version it found and how many data models it read. Do not extract or edit the file first.
4. Environments on that version now show "CIM ready". If an environment runs a version you have not uploaded, it says which version to upload, and only CIM mapping waits; parsing still works.

Supported CIM versions follow the table in section 2: 6.3.0 or later on Splunk 10.2 to 10.6, and 8.5.0 or later on 10.7 and later. Upload one package per version you run. The package stays inside this Parsemaxxing and is never shared.

If a customer has changed the data models in their own Splunk (added fields or edited constraints), the environment page shows the differences, and you choose which definitions Parsemaxxing uses for that environment.

The PDFs below add the full explanations behind those settings. They noticeably help with timestamps, multi-line events, CIM mapping and distributed deployments.

## 2. Rules before you download

- **Download them yourself, under your own Splunk access.** Splunk lets you download one copy of material it offers for download, for your own use. Each Parsemaxxing install should use PDFs its own team downloaded.
- **Keep them inside your install.** Never commit them to a repository, attach them to tickets, or share the files with other organizations. Parsemaxxing stores them only in its own database.
- **Do not edit the PDFs.** Import them exactly as downloaded.
- **Supported versions: Splunk Enterprise 10.2 and later** (10.2, 10.4, 10.6). Parsemaxxing does not support older versions, so do not download manuals for them; they would be refused at import.
- **Supported CIM add-on versions** depend on the Splunk version:

  | Splunk Enterprise | CIM add-on (`Splunk_SA_CIM`) |
  | --- | --- |
  | 10.2, 10.4, 10.6 | 6.3.0 or later |
  | 10.7 and later | 8.5.0 or later |

  Download the CIM manual for the CIM version you actually run (the manual's selector offers 6.3, 6.4 and 8.5 to 8.8). If an environment's CIM add-on is older than the minimum, Parsemaxxing still builds parsing for it but skips CIM mapping there until the add-on is upgraded.
- **Match the version.** Pick the version in the manual's version selector that matches the Splunk Enterprise version of your environments (and, for the CIM manual, the version of the CIM add-on). If you run several supported versions, download a set for each version.

How to find your versions:
- Splunk Enterprise: in Splunk Web, **Help → About**, or run `$SPLUNK_HOME/bin/splunk version`.
- CIM add-on: **Apps → Manage Apps**, find "Splunk Common Information Model", read the Version column. Parsemaxxing also shows both on each environment's page.

## 3. The manuals to download

Open each link and choose your version (10.2 or later) in the version selector. Then download in one of two ways:

- **Whole manual (recommended, one file per manual):** use the **PDF link in the manual's left-hand menu** (for example `Splunk_Data.pdf`). The file is large, which is fine: Parsemaxxing splits it by its own headings. The link is created for your visit and expires after about a day, so download straight away and never save or share the link itself. Next time, start again from the manual page below.
- **Single topics (smaller knowledge base):** open a topic, add `?pdfdownload=true` to the end of its address, and save the page that opens as a PDF from your browser's print dialog. For example, for the topic "How timestamp assignment works" in Getting Data In 10.6:
  `https://help.splunk.com/en/splunk-enterprise/get-data-in/get-started-with-getting-data-in/10.6/configure-timestamps/how-timestamp-assignment-works?pdfdownload=true`
  This takes more clicks, so use it only when you want selected chapters. For Getting Data In, the chapters that matter most are **Configure event processing**, **Configure timestamps**, **Configure indexed field extraction** and **Configure source types**.

You can mix both forms. If a topic is imported twice (once in a whole manual and once on its own), Parsemaxxing keeps one copy.

### Priority 1: parsing and CIM (download these first)

| Manual | Link | Version to pick | PDF name | What Parsemaxxing uses it for |
| --- | --- | --- | --- | --- |
| Getting Data In | [Open](https://help.splunk.com/en/splunk-enterprise/get-started/get-data-in) | Your Splunk Enterprise version | `Splunk_Data.pdf` | Line breaking, timestamps, time zones, character sets, sourcetypes, index-time field extraction, structured data |
| Knowledge Management Manual | [Open](https://help.splunk.com/en/splunk-enterprise/manage-knowledge-objects/knowledge-management-manual) | Your Splunk Enterprise version | `Splunk_Knowledge.pdf` | Search-time field extraction (`EXTRACT`, `REPORT`, `KV_MODE`), field aliases, calculated fields, lookups, event types, tags, the order of search-time operations |
| Common Information Model Add-on Manual | [Open](https://help.splunk.com/en/data-management/common-information-model) | Your CIM add-on version (6.3 or later; 8.5 or later on Splunk 10.7+) | `CIM_User.pdf` | Data model descriptions, field meanings, tags, how to normalize a new source |
| Admin Manual | [Open](https://help.splunk.com/en/splunk-enterprise/administer/admin-manual) | Your Splunk Enterprise version | `Splunk_Admin.pdf` | App structure, configuration file precedence, which pipeline phase uses which setting |

### Priority 2: distributed and clustered deployments (download if you have any non-standalone environment)

| Manual | Link | Version to pick | PDF name | What Parsemaxxing uses it for |
| --- | --- | --- | --- | --- |
| Distributed Deployment Manual | [Open](https://help.splunk.com/en/splunk-enterprise/administer/distributed-deployment-manual) | Your Splunk Enterprise version | `Splunk_Deploy.pdf` | Which component parses data, the data pipeline across tiers |
| Distributed Search | [Open](https://help.splunk.com/en/splunk-enterprise/administer/distributed-search) | Your Splunk Enterprise version | The PDF shown in the manual's menu, if offered | Search head clusters, the deployer, deployer push modes |
| Updating Splunk Enterprise Instances (deployment server; called "Agent management" in 10.x) | [Open](https://help.splunk.com/en/splunk-enterprise/administer/update-your-deployment) | Your Splunk Enterprise version | The PDF shown in the manual's menu, if offered | Server classes, deployment apps, reloads |
| Forwarding and Receiving Data | [Open](https://help.splunk.com/en/splunk-enterprise/forward-and-process-data/forwarding-and-receiving-data) | Your Splunk Enterprise version | The PDF shown in the manual's menu, if offered | Heavy forwarders, parsing and routing on forwarders |
| Universal Forwarder Manual | [Open](https://help.splunk.com/en/splunk-enterprise/forward-and-process-data/universal-forwarder-manual) | Your forwarder version | The PDF shown in the manual's menu, if offered | What forwarders do and do not parse, `EVENT_BREAKER` |
| Installing Splunk add-ons | [Open](https://help.splunk.com/en/supported-add-ons/about-the-splunk-supported-add-ons/installing-splunk-add-ons) | (not versioned) | The PDF shown in the menu, if offered | Which tier each kind of add-on content belongs on |

### Priority 3: optional

| Manual | Link | Version to pick | PDF name | What Parsemaxxing uses it for |
| --- | --- | --- | --- | --- |
| Manage Indexers and Indexer Clusters | [Open](https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters) | Your Splunk Enterprise version | `Splunk_Indexer.pdf` | Background on indexer clusters; Parsemaxxing never deploys to indexers, so this is reference only |
| Search Reference | [Open](https://help.splunk.com/en/splunk-enterprise/spl-search-reference) | Your Splunk Enterprise version | The PDF shown in the manual's menu, if offered | SPL commands used in discovery, drift alerts and validation searches |
| REST API Reference | [Open](https://help.splunk.com/en/splunk-enterprise/rest-api-reference) | Your Splunk Enterprise version | `Splunk_RESTREF.pdf` | Endpoints Parsemaxxing uses for connectivity, discovery and deployment |
| Securing Splunk Enterprise | [Open](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security) | Your Splunk Enterprise version | `Splunk_Security.pdf` | Roles, capabilities and tokens for Parsemaxxing's Splunk service accounts |

If a manual does not offer a PDF for your version, skip it. Parsemaxxing works without it.

## 4. Organize the files

Put each file in a folder per product, version and manual. Keep Splunk's file name for whole manuals; name topic PDFs after the topic:

```
knowledge-pdfs/
  splunk-enterprise/
    10.6/
      get-data-in/
        Splunk_Data.pdf                         (whole manual)
      knowledge-management/
        Splunk_Knowledge.pdf
      admin/
        Splunk_Admin.pdf
      distributed-deployment/
        Splunk_Deploy.pdf
    10.2/
      get-data-in/
        how-timestamp-assignment-works.pdf      (single topics)
        <another-topic-name>.pdf
  cim/
    8.8/
      CIM_User.pdf
```

The manual folder names Parsemaxxing recognizes are listed on the Knowledge → Overview page (`get-data-in`, `knowledge-management`, `cim`, `admin`, `distributed-deployment`, `indexer-clusters`, `distributed-search`, `deployment-server`, `forwarding`, `universal-forwarder`, `installing-add-ons`, `search-reference`, `rest-api`, `security`). Parsemaxxing reads the product, version and manual from the folders and checks them against the text of each PDF. If they disagree, it asks you before importing.

## 5. Load the PDFs into Parsemaxxing

You need the **admin** role.

### A. Server with internet or direct upload access

1. Go to **Knowledge → Sources → Import documents**.
2. Select the files or the whole `knowledge-pdfs` folder.
3. Check the detected product, manual and version for each file, and correct any that are wrong.
4. Select **Import**. The files are stored inside Parsemaxxing's database and appear in **Quarantine**.
5. Review the list and select **Approve**. Parsemaxxing splits each PDF into sections by its headings (tables kept whole), indexes them locally, and marks the source **Ready**.

The same file imported twice is recognized by its hash and skipped.

### B. Offline server (no internet)

On any machine where you can download the PDFs:

1. Download and organize the PDFs as in sections 3 and 4.
2. Build a signed pack with the Parsemaxxing command-line tool:
   ```
   parsemaxxing pack build ./knowledge-pdfs --out splunk-docs-10.6.tgz --key ./pack-signing.key
   ```
   The pack holds the PDFs, a manifest with each file's hash, product and version, and a signature.
3. Copy the `.tgz` to the offline server by your normal transfer process.

On the offline Parsemaxxing:

4. Register the matching public key once in **Settings → Knowledge → Pack signing keys**.
5. Go to **Knowledge → Sources → Import pack**, choose the `.tgz`. Parsemaxxing checks the signature and every file hash; a pack that fails either check is refused.
6. Approve it in **Quarantine**, as in section A.

Everything after import runs locally: the embedding model ships with Parsemaxxing, so no text or query leaves the server.

## 6. Set up retrieval (RAG)

In **Settings → Knowledge** (admin):

| Setting | Default | What it does |
| --- | --- | --- |
| Knowledge base | On | Turns retrieval on or off for all agents |
| Sources used | All approved | Turn individual tiers on or off: install files, agent skills, CIM definitions, project notes, imported documents, approved add-ons |
| Approved add-ons as examples | On | Can be turned off per customer (MSP) |
| References per agent call | 6 | Maximum sections given to an agent per call |
| Reference token budget | Set per stage | Keeps prompts small and costs predictable |
| Version matching | Strict | Only uses documents for the run's Splunk and CIM versions; "nearest" falls back to the closest version with a warning |

Then check it works:

1. Open **Knowledge → Test retrieval**.
2. Ask a question such as "How do I set the timestamp format for events with a time zone offset?" and pick the Splunk version.
3. You should see sections from `Getting Data In` and the `props.conf` spec entry for `TIME_FORMAT`, each with its source and version.
4. **Knowledge → Overview** shows each source's status, section count, versions covered, and a checklist of the Priority 1 and 2 manuals still missing for each environment's version.

During runs, the run workspace and the approval report show which sections the agents used, so you can open the source and check.

## 7. When you upgrade Splunk

- Download the manuals for the new version (10.2 or later) and import them as a new set.
- Keep the old set while any environment still runs the old version. Parsemaxxing picks the set that matches each environment.
- When no environment uses a version any more, Knowledge → Overview offers to retire that set.

## 8. Troubleshooting

| Problem | Cause and fix |
| --- | --- |
| "No text found" on import | The PDF is a scanned image. Download it again from the manual page; Splunk's PDFs contain text. |
| Wrong version detected | Rename the folder to the right version, or correct it in the import screen before approving. |
| "Version not supported" | The file is for Splunk Enterprise older than 10.2. Download the manual for a supported version. |
| Download link stopped working | Whole-manual PDF links expire after about a day. Open the manual page again and use the new PDF link. |
| File too large | The default limit is 100 MB and 3,000 pages per file (Settings → Knowledge). Raise it, or import the needed topics as single-topic PDFs. |
| Pack refused | The signature or a file hash does not match. Rebuild the pack with the same key, and check that the public key is registered. |
| Agents do not cite the manuals | Check the source is **Ready** (not in Quarantine), the version matches the environment, and the knowledge base is on. |

## 9. What not to do

- Do not put the PDFs, or text copied from them, in any repository, including private ones.
- Do not share a pack with another organization; each team builds its own.
- Do not import documents that contain customer data or secrets. The knowledge base is shared by every customer in this Parsemaxxing.
