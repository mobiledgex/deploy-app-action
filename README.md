# deploy-app-action
Github Action to deploy an app to the MobiledgeX Platform

## Inputs

### `setup`

**Required** The setup to deploy the app to. Default `"main"`.

### `username`

**Required** Console username

### `password`

**Required** Console password

### `appconfig`

**Required** Path to the app config file. Default `".mobiledgex/app.yml"`.

### `appinstsconfig`

**Required** Path to the app instances config file. Default `".mobiledgex/appinsts.yml"`.

## Outputs

### `image`

Image path for the app

### `deployments`

Comma-separated list of app instance deployments (if any)
