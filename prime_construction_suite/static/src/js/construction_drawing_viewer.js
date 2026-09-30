/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useRef, useState } from "@odoo/owl";

export class ConstructionDrawingMarkupViewer extends Component {
    static template = "prime_construction_suite.DrawingMarkupViewer";

    setup() {
        this.orm = useService("orm");
        this.imgRef = useRef("drawingImage");
        this.state = useState({
            revisionId: this.props.action.context.default_revision_id || false,
            revision: null,
            markups: [],
            imageData: null,
            pendingPin: null,   // {x, y}
            newComment: "",
            loading: true,
        });
        onWillStart(async () => {
            await this._load();
        });
    }

    async _load() {
        if (!this.state.revisionId) { this.state.loading = false; return; }
        this.state.loading = true;
        const [revision] = await this.orm.read('construction.drawing.revision',
            [this.state.revisionId], ['file', 'file_name', 'revision_code', 'drawing_id']);
        this.state.revision = revision;
        this.state.imageData = revision.file ? `data:image/*;base64,${revision.file}` : null;
        this.state.markups = await this.orm.searchRead('construction.drawing.markup',
            [['revision_id', '=', this.state.revisionId]],
            ['pos_x', 'pos_y', 'comment', 'author_id', 'resolved'], {order: 'id desc'});
        this.state.loading = false;
    }

    onImageClick(ev) {
        const rect = this.imgRef.el.getBoundingClientRect();
        const x = ((ev.clientX - rect.left) / rect.width) * 100;
        const y = ((ev.clientY - rect.top) / rect.height) * 100;
        this.state.pendingPin = {x, y};
        this.state.newComment = "";
    }

    setComment(ev) { this.state.newComment = ev.target.value; }

    async savePin() {
        if (!this.state.pendingPin || !this.state.newComment.trim()) return;
        await this.orm.create('construction.drawing.markup', [{
            revision_id: this.state.revisionId,
            pos_x: this.state.pendingPin.x,
            pos_y: this.state.pendingPin.y,
            comment: this.state.newComment,
        }]);
        this.state.pendingPin = null;
        this.state.newComment = "";
        await this._load();
    }

    cancelPin() { this.state.pendingPin = null; this.state.newComment = ""; }

    async toggleResolved(markup) {
        await this.orm.write('construction.drawing.markup', [markup.id], {resolved: !markup.resolved});
        await this._load();
    }
}

registry.category("actions").add("prime_construction_suite.drawing_markup_viewer", ConstructionDrawingMarkupViewer);
