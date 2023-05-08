# XRPLoop

![XRPLoop](branding/Default/PNG/Yellow/1000x/XRPLoop-Logo-Yellow1000.png "XRPLoop")
## About
The end of Coil left a hole in the WebMonetization and by extension the XRP communities. XRPLoop aims to allow XRP enabled services to recieve streamed micropayments from users with an XRP wallet.

Coils underlying ledger technology still runs on the XRPL. This application uses that to set up a [Payment Channel](https://xrpl.org/use-payment-channels.html) between the consumer/user and the service. The service then uses this to request micropayments when the front end client submits a payment notice.

## Status

Currently this code is proof of concept webmonetisation via XUMM. Over the coming months it will become somewhat more battle hardened and available to run as a microservice.

### TODO

Unsorted list:

- containerise the app for running in kubernetes
- distill app into clearer components, better modularisation of the code
- example UI components, front end installable as an independent script
- unit tests
- memos to record URL of the page (for accounting after the fact)
- payment/tip UI component
- better backend error handling & data processing
- async accounting function (write to local DB?)
  - third party payment propagation
  - service payment
- channel closing - both from expiration & user request
- UI to set the channel ammount
- more configuration options
  - frequency of payment
  - value of payment (ideally this is a formula...)
  - service wallet
- generate signature without accessing ledger
