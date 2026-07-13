# FlowForge MCP Data Model

## Core Entities

### Project

A project is the top-level container. It stores:

- a unique key
- a name
- an optional description
- a template reference

Projects also own their workflow statuses.

### Project Template

Templates define:

- the workflow status list
- starter tasks

The built-in `Default` template seeds the standard planning-to-done lifecycle.

### Project Status

Each project gets its own status records, copied from a template. Statuses carry flags such as:

- started
- blocked
- terminal
- reopened

### Work Unit

A Work Unit groups related tasks into a meaningful outcome. It can represent a feature, milestone, deliverable, or initiative.

Stored fields include:

- project reference
- key
- title
- description
- type
- status
- priority
- start date
- target date

### Task

Tasks are the atomic work items. They can either:

- belong to a Work Unit
- or live directly under a project

Tasks store:

- project reference
- optional Work Unit reference
- key
- title
- description
- status
- helpdesk reference
- priority
- assignee
- due date
- position

### Comment

Comments attach to tasks and record discussion or progress notes.

### Image Attachment

Attachments can belong to either:

- a task
- a comment

Each attachment stores:

- filename
- content type
- image bytes
- size
- optional alt text

### Tag

Tags are normalized to a case-insensitive canonical form and can be shared across tasks and work units.

## Relationships

- A project has many statuses.
- A project has many work units.
- A project has many tasks.
- A work unit has many tasks.
- A task has many comments.
- A task or comment has many image attachments.
- Tasks and work units can have many tags.

## Identity Rules

- Project keys are unique globally.
- Work Unit keys are unique within a project.
- Task keys are unique within a project.
- `helpdesk_ref_id` is unique within a project.

## Persistence Notes

The model is stored in SQLite and initialized automatically. Legacy databases are migrated by backfilling missing entity keys and creating the search index when possible.
